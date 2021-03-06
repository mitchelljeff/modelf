import tensorflow as tf


def tfprint(tensor, fun=None, prefix=""):
    """Prints tensor; optionally applies function first."""
    if fun is None:
        fun = lambda x: x
    return tf.Print(tensor, [fun(tensor)], prefix)


def tfprintshape(tensor, prefix=""):
    """Prints the shape of a tensor."""
    return tfprint(tensor, lambda x: tf.shape(x), prefix)


def tfrun(variables, feed_dict=None):
    """Executes variables in a new TensorFlow session, then returns results."""
    with tf.Session() as sess:
        sess.run(tf.initialize_all_variables())
        return sess.run(variables, feed_dict=feed_dict)


def get_last(tensor):
    """
    :param tensor: [dim1 x dim2 x dim3] tensor
    :return: [dim1 x dim3] tensor
    """
    shape = tf.shape(tensor)  # [dim1, dim2, dim3]
    slice_size = shape * [1, 0, 1] + [0, 1, 0]  # [dim1, 1 , dim3]
    slice_begin = shape * [0, 1, 0] + [0, -1, 0]  # [1, dim2-1, 1]
    return tf.squeeze(tf.slice(tensor, slice_begin, slice_size), [1])


def unit_length_transform(x, dim=1):
    """Normalizes x with L2 norm to unit length."""
    l2norm_sq = tf.reduce_sum(x * x, dim, keep_dims=True)
    l2norm = tf.rsqrt(l2norm_sq)
    #return x * tf.nn.l2_normalize(x, 0) #l2norm
    return x * l2norm
