from functools import wraps


def retry_on_error(ntries=2, function=None):

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            for i in range(1, ntries + 1):
                try:
                    print("\nExecuting {0:s} try {1:d}/{2:d}"
                          .format(f.__name__, i, ntries))
                    return f(*args, **kwargs)
                except Exception as e:
                    if not ntries == i:
                        print("{0:s} exception! Retrying {1:d}/{2:d}"
                              .format(type(e).__name__, (i + 1), ntries))
                        if function is not None:
                            function()
                    else:
                        print("{0:s} exception! Out of tries!"
                              .format(type(e).__name__))
        return wrapper
    return decorator
