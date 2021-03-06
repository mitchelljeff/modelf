import tensorflow as tf
from quebap.sisyphos.tfutil import tfrun
from quebap.sisyphos.models import get_total_trainable_variables, get_total_variables
import numpy as np
import operator, sys

SEED = 54321 #for random embedding initialization in NeuralVocab


class Vocab(object):
    """
    Vocab objects for use in sisyphos pipelines.

    Example:

        >>> #Test Vocab without pre-trained embeddings
        >>> vocab = Vocab()
        >>> print(vocab("blah"))
        1
        >>> print(vocab("bluh"))
        2
        >>> print(vocab("bleh"))
        3
        >>> print(vocab("bluh"))
        2
        >>> print(vocab("hello"))
        4
        >>> print(vocab("world"))
        5

        >>> #Sym2id before freezing:
        >>> for k in sorted(vocab.sym2id.keys()):
        ...     print(k,' : ',vocab.sym2id[k])
        <UNK>  :  0
        blah  :  1
        bleh  :  3
        bluh  :  2
        hello  :  4
        world  :  5

        >>> #Sym2id after freezing (no difference, because no pre-trained embeddings used):
        >>> vocab.freeze()
        >>> for k in sorted(vocab.sym2id.keys()):
        ...     print(k,' : ',vocab.sym2id[k])
        <UNK>  :  0
        blah  :  1
        bleh  :  3
        bluh  :  2
        hello  :  4
        world  :  5

        >>> #Test Vocab with pre-trained embeddings
        >>> def emb(w):
        ...    v = {'blah':[1.7,0,.3],'bluh':[0,1.5,0.5],'bleh':[0,0,2]}
        ...    return None if not w in v else v[w]
        >>> vocab = Vocab(emb=emb)
        >>> print(vocab("blah"))
        -1
        >>> print(vocab("bluh"))
        -2
        >>> print(vocab("bleh"))
        -3
        >>> print(vocab("bluh"))
        -2
        >>> print(vocab("hello"))
        1
        >>> print(vocab("world"))
        2

        >>> #Sym2id before freezing:
        >>> for k in sorted(vocab.sym2id.keys()):
        ...     print(k,' : ',vocab.sym2id[k])
        <UNK>  :  0
        blah  :  -1
        bleh  :  -3
        bluh  :  -2
        hello  :  1
        world  :  2

        >>> #Sym2id after freezing: normalized (positive) ids, also for pre-trained terms
        >>> vocab.freeze()
        >>> for k in sorted(vocab.sym2id.keys()):
        ...     print(k,' : ',vocab.sym2id[k])
        <UNK>  :  0
        blah  :  3
        bleh  :  5
        bluh  :  4
        hello  :  1
        world  :  2

        >>> #Test pretrained and out-of-vocab id's before freezing
        >>> vocab.unfreeze()
        >>> vocab.get_ids_pretrained()
        [-1, -2, -3]
        >>> vocab.get_ids_oov()
        [0, 1, 2]

        >>> #Test pretrained and out-of-vocab id's after freezing
        >>> vocab.freeze()
        >>> vocab.get_ids_pretrained()
        [3, 4, 5]
        >>> vocab.get_ids_oov()
        [0, 1, 2]

        >>> #Test calling frozen Vocab object
        >>> vocab(['bluh','world','wake','up']) #last 2 are new words, hence unknown
        [4, 2, 0, 0]

        >>> #Test calling unfrozen Vocab object
        >>> vocab.unfreeze()
        >>> vocab(['bluh','world','wake','up']) #last 2 are new words, hence added to Vocab
        [-2, 2, 3, 4]

        >>> #Test sym2id after freezing again
        >>> vocab.freeze()
        >>> for k in sorted(vocab.sym2id.keys()):
        ...     print(k,' : ',vocab.sym2id[k])
        <UNK>  :  0
        blah  :  5
        bleh  :  7
        bluh  :  6
        hello  :  1
        up  :  4
        wake  :  3
        world  :  2
    """

    DEFAULT_UNK = "<UNK>"

    def __init__(self, unk=DEFAULT_UNK, emb=None):
        """
        Creates Vocab object.

        Args:
            `unk`: symbol for unknown term (default: "<UNK>").
              If set to `None`, and `None` is not included as symbol while unfrozen,
              it will return `None` upon calling `get_id(None)` when frozen.
            `emb`: function handle; returns pre-trained embedding (fixed-size numerical list or ndarray)
              for a given symbol, and None for unknown symbols.
        """
        if unk is None:
            self.sym2id = {}
            self.id2sym = {} #with pos and neg indices
            self.next_pos = 0
            self.sym2freqs = {}
        else:
            self.sym2id = {unk: 0}
            self.id2sym = {0: unk} #with pos and neg indices
            self.next_pos = 1
            self.sym2freqs = {unk: 0}

        self.next_neg = -1
        self.unk = unk
        self.emb = emb if emb is not None else lambda _:None #if emb is None: same behavior as for o-o-v words
        self.emb_length = None
        self.frozen = False

    def freeze(self):
        """Freeze current Vocab object (set `self.frozen` to True).
        To be used after loading symbols from a given corpus;
        transforms all internal symbol id's to positive indices (for use in tensors).

        - additional calls to the __call__ method will return the id for the unknown symbold
        - out-of-vocab id's are positive integers and do not change
        - id's of symbols with pre-trained embeddings are converted to positive integer id's,
          counting up from the all out-of-vocab id's.
        """
        if not self.frozen and self.next_neg < -1: #if any pretrained have been encountered
            sym2id = {sym: self._normalize(id) for sym,id in self.sym2id.items()}
            id2sym = {self._normalize(id): sym for id,sym in self.id2sym.items()}
            self.sym2id = sym2id
            self.id2sym = id2sym
        self.frozen = True

    def unfreeze(self):
        """Unfreeze current Vocab object (set `self.frozen` to False).
        Caution: use with care! Unfreezing a Vocab, adding new terms, and again Freezing it,
        will result in shifted id's for pre-trained symbols.

        - maps all normalized id's to the original internal id's.
        - additional calls to __call__ will allow adding new symbols to the vocabulary.
        """
        if self.frozen and self.next_neg < -1:
            sym2id = {sym: self._denormalize(id) for sym, id in self.sym2id.items()}
            id2sym = {self._denormalize(id): sym for id, sym in self.id2sym.items()}
            self.sym2id = sym2id
            self.id2sym = id2sym
        self.frozen = False

    def get_id(self, sym):
        """
        Returns the id of `sym`; different behavior depending on the state of the Vocab:

        - In case self.frozen==False (default): returns internal id,
          that is, positive for out-of-vocab symbol, negative for symbol
          found in `self.emb`. If `sym` is a new symbol, it is added to the Vocab.

        - In case self.frozen==True (after explicit call to 'freeze()', or after building a `NeuralVocab` with it):
          Returns normalized id (positive integer, also for symbols with pre-trained embedding)
          If `sym` is a new symbol, the id for unknown terms is returned, if available,
          and otherwise `None` (only possible when input argument `unk` for `Vocab.__init__()` was set to `None`, e.g. ;
          for classification labels; it is assumed action is taken in the pipeline
          creating or calling the `Vocab` object, when `None` is encountered).

        Args:
            `sym`: symbol (e.g., token)
        """
        if not self.frozen:
            vec = self.emb(sym)
            if sym not in self.sym2id:
                if vec is None:
                    self.sym2id[sym] = self.next_pos
                    self.id2sym[self.next_pos] = sym
                    self.next_pos += 1
                else:
                    self.sym2id[sym] = self.next_neg
                    self.id2sym[self.next_neg] = sym
                    self.next_neg -= 1
                    self.emb_length = len(vec)
                self.sym2freqs[sym] = 1
            else:
                self.sym2freqs[sym] += 1
        if sym in self.sym2id:
            return self.sym2id[sym]
        else:
            if self.unk in self.sym2id:
                return self.sym2id[self.unk]
            else: #can happen for `Vocab` initialized with `unk` argument set to `None`
                return None

    def get_sym(self, id):
        """returns symbol for a given id (consistent with the `self.frozen` state), and None if not found."""
        return None if not id in self.id2sym else self.id2sym[id]

    def __call__(self, *args, **kwargs):
        """
        calls the `get_id` function for the provided symbol(s), which adds symbols to the Vocab if needed and allowed,
        and returns their id(s).

        Args:
            *args: a single symbol, a list of symbols, or multiple symbols
        """
        symbols = args
        if len(args) == 1:
            if isinstance(args[0], list):
                symbols = args[0]
            else:
                return self.get_id(args[0])
        return [self.get_id(sym) for sym in symbols]

    def __len__(self):
        """returns number of unique symbols (including the unknown symbol)"""
        return len(self.id2sym)

    def __contains__(self, sym):
        """checks if `sym` already in the Vocab object"""
        return sym in self.sym2id

    def _normalize(self,id):
        """map original (pos/neg) ids to normalized (non-neg) ids: first new symbols, then those in emb"""
        #e.g. -1 should be mapped to self.next_pos + 0
        #e.g. -3 should be mapped to self.next_pos + 2
        return id if id >=0 else self.next_pos - id - 1

    def _denormalize(self,id):
        #self.next_pos + i is mapped back to  -1-i
        return id if id < self.next_pos else -1-(id-self.next_pos)

    def get_ids_pretrained(self):
        """return internal or normalized id's (depending on frozen/unfrozen state)
        for symbols that have an embedding in `self.emb` """
        if self.frozen:
            return list(range(self.next_pos,self.next_pos+self.count_pretrained()))
        else:
            return list(range(-1,self.next_neg,-1))

    def get_ids_oov(self):
        """return out-of-vocab id's (indep. of frozen/unfrozen state)"""
        return list(range(self.next_pos))

    def count_pretrained(self):
        """equivalent to `len(get_ids_pretrained())`"""
        return -self.next_neg - 1

    def count_oov(self):
        """equivalent to `len(get_ids_oov())`"""
        return self.next_pos

    def prune(self, min_freq=5, max_size=sys.maxsize):
        """returns new Vocab object, pruned based on minimum symbol frequency"""
        pruned_vocab = Vocab(unk=self.unk, emb=self.emb)
        cnt = 0
        for sym, freq in sorted(self.sym2freqs.items(), key=operator.itemgetter(1), reverse=True):
        #for sym in self.sym2freqs:
            #freq = self.sym2freqs[sym]
            cnt += freq
            if freq >= min_freq and cnt <= max_size:
                pruned_vocab(sym)
                pruned_vocab.sym2freqs[sym] = freq
        if self.frozen:#if original Vocab was frozen, freeze new one
            pruned_vocab.freeze()

        return pruned_vocab


class NeuralVocab(Vocab):
    """
    Wrapper around Vocab to go from indices to tensors.

    Example:
        >>> #Start from same Vocab as the doctest example in Vocab
        >>> def emb(w):
        ...    v = {'blah':[1.7,0,.3],'bluh':[0,1.5,0.5],'bleh':[0,0,2]}
        ...    return None if not w in v else v[w]
        >>> vocab = Vocab(emb=emb)
        >>> vocab("blah", "bluh", "bleh", "hello", "world")  #symbols as multiple arguments
        [-1, -2, -3, 1, 2]
        >>> vocab(['bluh','world','wake','up']) #as list of symbols
        [-2, 2, 3, 4]

        >>> #Create NeuralVocab object
        >>> with tf.variable_scope('neural_test1'):
        ...     nvocab = NeuralVocab(vocab, None, 3, unit_normalize=True)
        ...     tfrun(nvocab(vocab("world")))
        array([ 0.35790324, -0.15442504,  0.31915373], dtype=float32)
        >>> tra1 = get_total_trainable_variables()


        >>> #Test NeuralVocab with pre-trained embeddings  (case: input_size larger than pre-trained embeddings)
        >>> with tf.variable_scope('neural_test2'):
        ...     for w in ['blah','bluh','bleh']:
        ...         w, emb(w)
        ...     nvocab = NeuralVocab(vocab, None, 4, unit_normalize=True, use_pretrained=True, train_pretrained=False)
        ...     tfrun(nvocab.embedding_matrix)
        ('blah', [1.7, 0, 0.3])
        ('bluh', [0, 1.5, 0.5])
        ('bleh', [0, 0, 2])
        array([[ 0.95993018,  0.06397769,  0.63649762,  0.01743277],
               [ 0.33867511, -0.1801414 , -0.01724755,  0.22024423],
               [ 0.05380315, -0.44075871,  0.64322513,  0.69728172],
               [ 0.16105628,  0.11053304, -0.23188654, -0.51288235],
               [-0.15421754,  0.22732525, -0.54268581,  0.67570436],
               [ 0.98478359,  0.        ,  0.17378533,  1.2295723 ],
               [ 0.        ,  0.94868326,  0.31622776, -0.68760252],
               [ 0.        ,  0.        ,  1.        , -0.23400906]], dtype=float32)
        >>> get_total_trainable_variables()-tra1
        23

    Interpretation of number of trainable variables from neural_test2:
    out-of-vocab: 8 - 3 = 5 symbols, with each 4 dimensions = 20;
    for fixed pre-trained embeddings with length 3, three times 1 extra trainable dimension for total embedding length 4.
    Total is 23.
    """


    def __init__(self, base_vocab, embedding_matrix=None,
                 input_size=None, reduced_input_size=None, use_pretrained=True, train_pretrained=False, unit_normalize=True, seed=SEED):
        """
        Creates NeuralVocab object from a given Vocab object `base_vocab`.
        Pre-calculates embedding vector (as `Tensor` object) for each symbol in Vocab


        Args:
            `base_vocab`:
            `embedding_matrix`: tensor with shape (len_vocab, input_size). If provided,
              the arguments `input_size`, `use_trained`, `train_pretrained`, and `unit_normalize` are ignored.
            `input_size`: integer; embedding length in case embedding matrix not provided, else ignored.
              If shorter than pre-trained embeddings, only their first `input_size` dimensions are used.
              If longer, extra (Trainable) dimensions are added.
            `reduced_input_size`: integer; optional; ignored in case `None`. If set to positive integer, an additional
              linear layer is introduced to reduce (or extend) the embeddings to the indicated size.
            `use_pretrained`:  boolean; True (default): use pre-trained if available through `base_vocab`.
              False: ignore pre-trained embeddings accessible through `base_vocab`
            `train_pretrained`: boolean; False (default): fix pretrained embeddings. True: continue training.
              Ignored if embedding_matrix is given.
            `unit_normalize`: initialize pre-trained vectors with unit norm
              (note: randomly initialized embeddings are always initialized with expected unit norm)
        """
        super(NeuralVocab, self).__init__(unk=base_vocab.unk, emb=base_vocab.emb)
        np.random.seed(seed)
        tf.set_random_seed(seed)

        assert (embedding_matrix, input_size) is not (None, None), "if no embedding_matrix is provided, define input_size"

        self.freeze() #has no actual functionality here
        base_vocab.freeze() #freeze if not frozen (to ensure fixed non-negative indices)

        self.sym2id = base_vocab.sym2id
        self.id2sym = base_vocab.id2sym
        self.sym2freqs = base_vocab.sym2freqs
        self.unit_normalize = unit_normalize

        np_normalize = lambda v: v/np.sqrt(np.sum(np.square(v)))

        if embedding_matrix is None:
            #construct part oov
            n_oov = base_vocab.count_oov()
            n_pre = base_vocab.count_pretrained()
            E_oov = tf.get_variable("embeddings_oov", [n_oov, input_size],
                                     initializer=tf.random_normal_initializer(0, 1./np.sqrt(input_size)),
                                     trainable=True, dtype="float32")
            #stdev = 1/sqrt(length): then expected initial L2 norm is 1

            #construct part pretrained
            if use_pretrained and base_vocab.emb_length is not None:
                #load embeddings into numpy tensor with shape (count_pretrained, min(input_size,emb_length))
                np_E_pre = np.zeros([n_pre, min(input_size, base_vocab.emb_length)]).astype("float32")
                for id in base_vocab.get_ids_pretrained():
                    sym = base_vocab.id2sym[id]
                    i = id - n_oov  #shifted to start from 0
                    np_E_pre[i,:] = base_vocab.emb(sym)[:min(input_size,base_vocab.emb_length)]
                    if unit_normalize:
                        np_E_pre[i,:] = np_normalize(np_E_pre[i,:])
                E_pre = tf.get_variable("embeddings_pretrained", initializer=tf.identity(np_E_pre),
                                        trainable=False, dtype="float32")

                if input_size > base_vocab.emb_length:
                    E_pre_ext = tf.get_variable("embeddings_extra", [n_pre, input_size-base_vocab.emb_length],
                        initializer=tf.random_normal_initializer(0.0, 1./np.sqrt(base_vocab.emb_length)), dtype="float32", trainable=True)
                    #note: stdev = 1/sqrt(emb_length) means: elements from same normal distr. as normalized first part (in case normally distr.)
                    E_pre = tf.concat(1, [E_pre, E_pre_ext], name="embeddings_pretrained_extended")

            else: #initialize all randomly anyway
                E_pre = tf.get_variable("embeddings_not_pretrained", [n_pre, input_size],
                                        initializer=tf.random_normal_initializer(0., 1./np.sqrt(input_size)),
                                        trainable=True, dtype="float32")
                #again: initialize with expected unit norm

            self.input_size = input_size   #must be provided is embedding_matrix is None
            self.embedding_matrix = tf.concat(0, [E_oov, E_pre], name="embeddings")

        else:
            self.input_size = embedding_matrix.get_shape()[1] #ignore input argument input_size
            self.embedding_matrix = embedding_matrix

        if isinstance(reduced_input_size, int) and reduced_input_size > 0:
            init = tf.contrib.layers.xavier_initializer(uniform=True)  # uniform=False for truncated normal
            self.embedding_matrix = tf.contrib.layers.fully_connected(self.embedding_matrix, reduced_input_size,
                                                       weights_initializer=init,activation_fn=None)

        #pre-assign embedding vectors to all ids
        self.id2vec = [tf.nn.embedding_lookup(self.embedding_matrix, id) for id in range(len(self))] #always OK if frozen



    def embed_symbol(self, id):
        """returns embedded id's

        Args:
            `id`: integer, ndarray with np.int32 integers,
                  or tensor with tf.int32 integers.
            These integers correspond to (normalized) id's for symbols in `self.base_vocab`.

        Returns:
            tensor with id's embedded by numerical vectors (in last dimension)
        """
        return tf.nn.embedding_lookup(self.embedding_matrix, id)


    def __call__(self, *args, **kwargs):
        """
        Calling the NeuralVocab object with symbol id's,
        returns a `Tensor` with corresponding embeddings.

        Args:
            `*args`: `Tensor` with integer indices
              (such as a placeholder, to be evaluated when run in a `tf.Session`),
              or list of integer id's,
              or just multiple integer ids as input arguments

        Returns:
            Embedded `Tensor` in case a `Tensor` was provided as input,
            and otherwise a list of embedded input id's under the form of fixed-length embeddings (`Tensor` objects).
        """
        if len(args) == 1:  #tuple with length 1: then either list with ids, tensor with ids, or single id
            if isinstance(args[0], list):
                ids = args[0]
            elif tf.contrib.framework.is_tensor(args[0]):
                #return embedded tensor
                return self.embed_symbol(args[0])
            else:
                return self.id2vec[args[0]]
        else: #tuple with ids
            ids = args
        return [self.id2vec[id] for id in ids]

    def get_embedding_matrix(self):
        return self.embedding_matrix




if __name__ == '__main__':

    print('perform doctest verification of functionality.')

    import doctest
    print(doctest.testmod())

