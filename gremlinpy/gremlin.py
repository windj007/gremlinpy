import uuid

from .exception import *
from .statement import Statement
from .config import GRAPH_VARIABLE


_PREDICATES = []


class LinkList(object):
    top = None
    bottom = None

    def add(self, link):
        self.bottom.next = link
        self.bottom = link

        return self

    def remove(self, link, drop_after=False):
        next = None
        token = self.top

        while token:
            if link == token:
                if drop_after:
                    token.bottom = None
                    break
                else:
                    token.bottom = token.next.next if token.next else None

            token = token.next

        return self

    def can_use(self, prev, link):
        return True

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        token = self.top
        prev = token
        tokens = []
        variable = ''

        """
        prepare the gremlin string
            use the token's concat value only if the preceeding token is
            not Raw or an empty string (this happens when the graph variable
            is set to ''
        """
        while token:
            string = str(token)
            next = token.next

            if len(tokens) and token.concat and self.can_use(prev, token):
                if type(prev) == GraphVariable:
                    append = len(tokens[-1]) > 0
                else:
                    append = True

                if append:
                    tokens.append(token.concat)

            tokens.append(string)

            prev = token
            token = token.next

        return '%s%s' % (variable, ''.join(tokens))


class Link(object):
    next = None


class Gremlin(LinkList):
    PARAM_PREFIX = 'GPY_PARAM'

    def __init__(self, graph_variable=GRAPH_VARIABLE):
        self.gv = graph_variable
        self.top = GraphVariable(self, graph_variable)

        self.reset()

    def reset(self):
        self.parent = None
        self.bottom = self.top
        self.bound_params = {}
        self.bound_param = str(uuid.uuid4())[-5:]
        self.bound_count = 0
        self.top.next = None
        self.return_var = None

        return self.set_graph_variable(self.gv)

    def can_use(self, prev, link):
        return type(prev) is not Raw

    def __unicode__(self):
        string = super(Gremlin, self).__unicode__()
        variable = ''

        if self.return_var is not None:
            variable = '%s = ' % self.return_var

        return '%s%s' % (variable, string)

    def __getattr__(self, attr):
        attr = Attribute(self, attr)

        return self.add_token(attr)

    def __call__(self, *args):
        func = Function(self, str(self.bottom), tuple(args))
        self.bottom.next = func

        return self.remove_token(self.bottom).add_token(func)

    def __getitem__(self, val):
        if not isinstance(val, slice):
            val = val if type(val) is list or type(val) is tuple else [val]
    
            try:
                start = val[0]
            except Exception as e:
                start = None
    
            try:
                end = val[1]
            except Exception as e:
                end = None
    
            try:
                step = val[2]
            except Exception as e:
                step = None

            val = slice(start, end, step)

        index = Index(self, val)

        return self.add_token(index)

    def set_parent_gremlin(self, gremlin):
        self.parent = gremlin

        return self.bind_params(self.bound_params)

    def bind_params(self, params=None):
        if params is None:
            params = []

        for value in params:
            self.bind_param(value)

        return self.bound_params

    def bind_param(self, value, name=None):
        self.bound_count += 1

        if value in self.bound_params:
            name = value
            value = self.bound_params[value]

        if name is None:
            name = '%s_%s_%s' % (self.PARAM_PREFIX, self.bound_param, \
                self.bound_count)

        self.bound_params[name] = value

        if self.parent is not None:
            self.parent.bind_param(value, name)

        return (name, value)

    def range(self, start, end):
        return self.func_raw_unbound('range', *(start, end))

    def unbound(self, function, *args):
        unbound = UnboudFunction(self, function, args)

        return self.add_token(unbound)

    def func(self, function, *args):
        func = Function(self, function, tuple(args))
        
        return self.add_token(func)

    def func_raw(self, function, *args):
        func_raw = FunctionRaw(self, function, args)

        return self.add_token(func_raw)

    def func_raw_unbound(self, function, *args):
        func_raw = UnboudFunctionRaw(self, function, args)

        return self.add_token(func_raw)

    def close(self, value, *args):
        if args:
            close = ClosureArguments(self, value, args)
        else:
            close = Closure(self, value)

        return self.add_token(close)

    def raw(self, value):
        raw = Raw(self, value)

        return self.add_token(raw)

    def add_token(self, token):
        self.bottom.next = token
        self.bottom = token

        return self

    def remove_token(self, remove):
        token = self.top

        while token:
            if token.next == remove:
                token.next = token.next.next
                break

            token = token.next

        return self

    def set_ret_variable(self, return_var=None):
        self.return_var = return_var

        return self

    def set_graph_variable(self, graph_variable='g'):
        if not graph_variable:
            graph_variable = ''

        self.top.value = graph_variable

        return self

    def apply_statement(self, statement):
        statement.set_gremlin(self).build()

        return self


class _Tokenable(object):

    def __str__(self):
        return str(self.__unicode__())

    def __unicode__(self):
        return self.value

    def apply_statement(self, statement):
        if hasattr(statement, 'gremlin') == False:
            statement.set_gremlin(Gremlin())

        statement.gremlin.set_parent_gremlin(self.gremlin)

        return statement

    def fix_value(self, value, can_bind = False):
        if isinstance(value, Predicate):
            value.gremlin = Gremlin(self.gremlin.gv)
            return value
        elif isinstance(value, (list, tuple)):
            value = [self.fix_value(a, can_bind = can_bind) for a in value]
            return value
        elif issubclass(type(value), Statement): 
            self.apply_statment(value)
            return value
        elif issubclass(type(value), Gremlin):
            value.set_parent_gremlin(self.gremlin)
            return value
        elif can_bind and not getattr(self, 'gremlin', None) is None and isinstance(value, (int, str, unicode, float, bool)):
            return self.gremlin.bind_param(value)[0]
        else:
            return value


class Token(Link, _Tokenable):
    next = None
    value = None
    args = []
    concat = ''
    can_bind = False

    def __init__(self, gremlin, value, args=None):
        self.gremlin = gremlin
        self.value = self.fix_value(value)

        if args is None:
            args = ()

        self.args = self.fix_value(tuple(args), can_bind = self.can_bind)


class GraphVariable(Token):

    def __unicode__(self):
        if self.value == '':
            self.concat = ''

        return self.value


class Attribute(Token):
    concat = '.'


class Function(Token):
    """
    class used to create a Gremlin function
    it assumes that the last argument passed to the function is the only thing
    that will be bound
    if you need more than the last argument bound, you can do:

        g = Gremlin()
        value1 = g.bind_param('value1')[0]
        value2 = g.bind_param('value2')[0]
        g.functionName('not_bound', value1, value2, ...)
    """
    concat = '.'
    can_bind = True 

    def __unicode__(self):
        params = []

        if len(self.args):
            bound = self.args.pop()
            params = self.args

            if issubclass(type(bound), Statement):
                self.apply_statment(bound)

                params.append(str(bound))
            elif issubclass(type(bound), Gremlin):
                bound.set_parent_gremlin(self.gremlin)
                
                params.append(str(bound))
            else:
                params.append(str(bound))
        return '%s(%s)' % (self.value, ', '.join(map(str, params)))


class FunctionRaw(Function):
    concat = ''


class UnboudFunction(Token):
    concat = '.'
    can_bind = False

    def __unicode__(self):
        return '%s(%s)' % (self.value, ', '.join(self.args))


class UnboudFunctionRaw(UnboudFunction):
    concat = ''


class Index(Token):

    def __unicode__(self):
        if self.value.stop is not None:
            index = '[%s..%s]' % (self.value.start, self.value.stop)
        else:
            index = '[%s]' % self.value.start

        return index


class Closure(Token):

    def __unicode__(self):
        if type(self.value) is Statement:
            self.gremlin.apply_statment(self.value)

            self.value = str(self.gremlin)
        elif type(self.value) is Gremlin:
            self.value.set_parent_gremlin(self.gremlin)

        return '{%s}' % str(self.value)


class ClosureArguments(Token):

    def __unicode__(self):
        if type(self.value) is Statement:
            self.gremlin.apply_statment(self.value)

            self.value = str(self.gremlin)
        elif type(self.value) is Gremlin:
            self.value.set_parent_gremlin(self.gremlin)

        return '{%s -> %s}' % (','.join(self.args), str(self.value))


class Raw(Token):

    def __unicode__(self):
        if issubclass(type(self.value), Statement):
            self.apply_statement(self.value)

            self.value = str(self.value)
        elif type(self.value) is Gremlin:
            self.value.set_parent_gremlin(self.gremlin)

        return str(self.value)


def _p(name, *args):
    pred = Predicate(*args)
    pred._function = name

    return pred


class Predicate(_Tokenable, LinkList):

    def __init__(self, *args):
        self.args = self.fix_value(list(args))

    def __unicode__(self):
        if not self._function:
            error = '%s predicate does not have a _function defined' % self.__class__.__name__
            raise PredicateError(error)

        return '%s(%s)' % (self._function, ', '.join(self.args))

    def __getattr__(self, predicate_name):
        self.predicate_name = predicate_name
        return self

    def __call__(self, *args):
        print('PRED', self.predicate_name, args)


class _NamedPredicate(Predicate):

    @property
    def _function(self):
        return self.__class__.__name__


class eq(_NamedPredicate):
    pass


class neq(_NamedPredicate):
    pass


class lt(_NamedPredicate):
    pass


class lte(_NamedPredicate):
    pass


class gt(_NamedPredicate):
    pass


class gte(_NamedPredicate):
    pass


class inside(_NamedPredicate):
    pass


class outside(_NamedPredicate):
    pass


class between(_NamedPredicate):
    pass


class within(_NamedPredicate):
    pass


class without(_NamedPredicate):
    pass
