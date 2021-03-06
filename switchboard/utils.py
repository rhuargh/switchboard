
import sys
import importlib

# Make input function python2 and 3 compatible
try:
    input = raw_input
except NameError:
    pass

def get_input(prompt=''):
    return input(prompt)


def determine_if_class_method(frames):
    ''' Bit of a hacky way to determine if the decorated function is
        defined in a class or is standalone. See:
        http://stackoverflow.com/questions/8793233/python-can-a-decorator-determine-if-a-function-is-being-defined-inside-a-class '''

    if len(frames) > 2:
        maybe_class_frame = frames[2]
        statement_list = maybe_class_frame[4]
        if statement_list:
            first_statment = statement_list[0]
            if first_statment.strip().startswith('class '):
                return True

    return False


def load_attribute(attribute):
    ''' Loads or reloads the given attribute. For example:

        1) load_attribute('module.submodule.class_name')

            will return the type class_name (but not instantiate it)
            from the module 'module.submodule'

        2) load_attribute('module.submodule.func_name')

            will return the function from that same module. '''

    attribute_name = attribute.split('.')[-1]
    pymodule = '.'.join(attribute.split('.')[:-1])

    if pymodule in sys.modules:
        pymodule_instance = importlib.reload(sys.modules[pymodule])
    else:
        pymodule_instance = importlib.import_module(pymodule)

    # Get the attribute and return it
    return getattr(pymodule_instance, attribute_name)
