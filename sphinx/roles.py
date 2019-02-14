"""
    sphinx.roles
    ~~~~~~~~~~~~

    Handlers for additional ReST roles.

    :copyright: Copyright 2007-2019 by the Sphinx team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""

import re
import warnings

from docutils import nodes, utils

from sphinx import addnodes
from sphinx.deprecation import RemovedInSphinx40Warning
from sphinx.errors import SphinxError
from sphinx.locale import _
from sphinx.util import ws_re
from sphinx.util.docutils import ReferenceRole, SphinxRole
from sphinx.util.nodes import split_explicit_title, process_index_entry, \
    set_role_source_info

if False:
    # For type annotation
    from typing import Any, Dict, List, Tuple, Type  # NOQA
    from docutils.parsers.rst.states import Inliner  # NOQA
    from sphinx.application import Sphinx  # NOQA
    from sphinx.environment import BuildEnvironment  # NOQA
    from sphinx.util.typing import RoleFunction  # NOQA


generic_docroles = {
    'command': addnodes.literal_strong,
    'dfn': nodes.emphasis,
    'kbd': nodes.literal,
    'mailheader': addnodes.literal_emphasis,
    'makevar': addnodes.literal_strong,
    'manpage': addnodes.manpage,
    'mimetype': addnodes.literal_emphasis,
    'newsgroup': addnodes.literal_emphasis,
    'program': addnodes.literal_strong,  # XXX should be an x-ref
    'regexp': nodes.literal,
}


# -- generic cross-reference role ----------------------------------------------

class XRefRole:
    """
    A generic cross-referencing role.  To create a callable that can be used as
    a role function, create an instance of this class.

    The general features of this role are:

    * Automatic creation of a reference and a content node.
    * Optional separation of title and target with `title <target>`.
    * The implementation is a class rather than a function to make
      customization easier.

    Customization can be done in two ways:

    * Supplying constructor parameters:
      * `fix_parens` to normalize parentheses (strip from target, and add to
        title if configured)
      * `lowercase` to lowercase the target
      * `nodeclass` and `innernodeclass` select the node classes for
        the reference and the content node

    * Subclassing and overwriting `process_link()` and/or `result_nodes()`.
    """

    nodeclass = addnodes.pending_xref   # type: Type[nodes.Element]
    innernodeclass = nodes.literal      # type: Type[nodes.TextElement]

    def __init__(self, fix_parens=False, lowercase=False,
                 nodeclass=None, innernodeclass=None, warn_dangling=False):
        # type: (bool, bool, Type[nodes.Element], Type[nodes.TextElement], bool) -> None
        self.fix_parens = fix_parens
        self.lowercase = lowercase
        self.warn_dangling = warn_dangling
        if nodeclass is not None:
            self.nodeclass = nodeclass
        if innernodeclass is not None:
            self.innernodeclass = innernodeclass

    def _fix_parens(self, env, has_explicit_title, title, target):
        # type: (BuildEnvironment, bool, str, str) -> Tuple[str, str]
        if not has_explicit_title:
            if title.endswith('()'):
                # remove parentheses
                title = title[:-2]
            if env.config.add_function_parentheses:
                # add them back to all occurrences if configured
                title += '()'
        # remove parentheses from the target too
        if target.endswith('()'):
            target = target[:-2]
        return title, target

    def __call__(self, typ, rawtext, text, lineno, inliner,
                 options={}, content=[]):
        # type: (str, str, str, int, Inliner, Dict, List[str]) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
        env = inliner.document.settings.env
        if not typ:
            typ = env.temp_data.get('default_role')
            if not typ:
                typ = env.config.default_role
            if not typ:
                raise SphinxError('cannot determine default role!')
        else:
            typ = typ.lower()
        if ':' not in typ:
            domain, role = '', typ
            classes = ['xref', role]
        else:
            domain, role = typ.split(':', 1)
            classes = ['xref', domain, '%s-%s' % (domain, role)]
        # if the first character is a bang, don't cross-reference at all
        if text[0:1] == '!':
            text = utils.unescape(text)[1:]
            if self.fix_parens:
                text, tgt = self._fix_parens(env, False, text, "")
            innernode = self.innernodeclass(rawtext, text, classes=classes)
            return self.result_nodes(inliner.document, env, innernode, is_ref=False)
        # split title and target in role content
        has_explicit_title, title, target = split_explicit_title(text)
        title = utils.unescape(title)
        target = utils.unescape(target)
        # fix-up title and target
        if self.lowercase:
            target = target.lower()
        if self.fix_parens:
            title, target = self._fix_parens(
                env, has_explicit_title, title, target)
        # create the reference node
        refnode = self.nodeclass(rawtext, reftype=role, refdomain=domain,
                                 refexplicit=has_explicit_title)
        # we may need the line number for warnings
        set_role_source_info(inliner, lineno, refnode)
        title, target = self.process_link(env, refnode, has_explicit_title, title, target)
        # now that the target and title are finally determined, set them
        refnode['reftarget'] = target
        refnode += self.innernodeclass(rawtext, title, classes=classes)
        # we also need the source document
        refnode['refdoc'] = env.docname
        refnode['refwarn'] = self.warn_dangling
        # result_nodes allow further modification of return values
        return self.result_nodes(inliner.document, env, refnode, is_ref=True)

    # methods that can be overwritten

    def process_link(self, env, refnode, has_explicit_title, title, target):
        # type: (BuildEnvironment, nodes.Element, bool, str, str) -> Tuple[str, str]
        """Called after parsing title and target text, and creating the
        reference node (given in *refnode*).  This method can alter the
        reference node and must return a new (or the same) ``(title, target)``
        tuple.
        """
        return title, ws_re.sub(' ', target)

    def result_nodes(self, document, env, node, is_ref):
        # type: (nodes.document, BuildEnvironment, nodes.Element, bool) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
        """Called before returning the finished nodes.  *node* is the reference
        node if one was created (*is_ref* is then true), else the content node.
        This method can add other nodes and must return a ``(nodes, messages)``
        tuple (the usual return value of a role function).
        """
        return [node], []


class AnyXRefRole(XRefRole):
    def process_link(self, env, refnode, has_explicit_title, title, target):
        # type: (BuildEnvironment, nodes.Element, bool, str, str) -> Tuple[str, str]
        result = super().process_link(env, refnode, has_explicit_title, title, target)
        # add all possible context info (i.e. std:program, py:module etc.)
        refnode.attributes.update(env.ref_context)
        return result


def indexmarkup_role(typ, rawtext, text, lineno, inliner, options={}, content=[]):
    # type: (str, str, str, int, Inliner, Dict, List[str]) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
    """Role for PEP/RFC references that generate an index entry."""
    warnings.warn('indexmarkup_role() is deprecated.  Please use PEP or RFC class instead.',
                  RemovedInSphinx40Warning, stacklevel=2)
    env = inliner.document.settings.env
    if not typ:
        assert env.temp_data['default_role']
        typ = env.temp_data['default_role'].lower()
    else:
        typ = typ.lower()

    has_explicit_title, title, target = split_explicit_title(text)
    title = utils.unescape(title)
    target = utils.unescape(target)
    targetid = 'index-%s' % env.new_serialno('index')
    indexnode = addnodes.index()
    targetnode = nodes.target('', '', ids=[targetid])
    inliner.document.note_explicit_target(targetnode)
    if typ == 'pep':
        indexnode['entries'] = [
            ('single', _('Python Enhancement Proposals; PEP %s') % target,
             targetid, '', None)]
        anchor = ''
        anchorindex = target.find('#')
        if anchorindex > 0:
            target, anchor = target[:anchorindex], target[anchorindex:]
        if not has_explicit_title:
            title = "PEP " + utils.unescape(title)
        try:
            pepnum = int(target)
        except ValueError:
            msg = inliner.reporter.error('invalid PEP number %s' % target,
                                         line=lineno)
            prb = inliner.problematic(rawtext, rawtext, msg)
            return [prb], [msg]
        ref = inliner.document.settings.pep_base_url + 'pep-%04d' % pepnum
        sn = nodes.strong(title, title)
        rn = nodes.reference('', '', internal=False, refuri=ref + anchor,
                             classes=[typ])
        rn += sn
        return [indexnode, targetnode, rn], []
    elif typ == 'rfc':
        indexnode['entries'] = [
            ('single', 'RFC; RFC %s' % target, targetid, '', None)]
        anchor = ''
        anchorindex = target.find('#')
        if anchorindex > 0:
            target, anchor = target[:anchorindex], target[anchorindex:]
        if not has_explicit_title:
            title = "RFC " + utils.unescape(title)
        try:
            rfcnum = int(target)
        except ValueError:
            msg = inliner.reporter.error('invalid RFC number %s' % target,
                                         line=lineno)
            prb = inliner.problematic(rawtext, rawtext, msg)
            return [prb], [msg]
        ref = inliner.document.settings.rfc_base_url + inliner.rfc_url % rfcnum
        sn = nodes.strong(title, title)
        rn = nodes.reference('', '', internal=False, refuri=ref + anchor,
                             classes=[typ])
        rn += sn
        return [indexnode, targetnode, rn], []
    else:
        raise ValueError('unknown role type: %s' % typ)


class PEP(ReferenceRole):
    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]
        target_id = 'index-%s' % self.env.new_serialno('index')
        entries = [('single', _('Python Enhancement Proposals; PEP %s') % self.target,
                    target_id, '', None)]

        index = addnodes.index(entries=entries)
        target = nodes.target('', '', ids=[target_id])
        self.inliner.document.note_explicit_target(target)

        try:
            refuri = self.build_uri()
            reference = nodes.reference('', '', internal=False, refuri=refuri, classes=['pep'])
            if self.has_explicit_title:
                reference += nodes.strong(self.title, self.title)
            else:
                title = "PEP " + self.title
                reference += nodes.strong(title, title)
        except ValueError:
            msg = self.inliner.reporter.error('invalid PEP number %s' % self.target,
                                              line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]

        return [index, target, reference], []

    def build_uri(self):
        # type: () -> str
        base_url = self.inliner.document.settings.pep_base_url
        ret = self.target.split('#', 1)
        if len(ret) == 2:
            return base_url + 'pep-%04d#%s' % (int(ret[0]), ret[1])
        else:
            return base_url + 'pep-%04d' % int(ret[0])


class RFC(ReferenceRole):
    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
        target_id = 'index-%s' % self.env.new_serialno('index')
        entries = [('single', 'RFC; RFC %s' % self.target, target_id, '', None)]

        index = addnodes.index(entries=entries)
        target = nodes.target('', '', ids=[target_id])
        self.inliner.document.note_explicit_target(target)

        try:
            refuri = self.build_uri()
            reference = nodes.reference('', '', internal=False, refuri=refuri, classes=['rfc'])
            if self.has_explicit_title:
                reference += nodes.strong(self.title, self.title)
            else:
                title = "RFC " + self.title
                reference += nodes.strong(title, title)
        except ValueError:
            msg = self.inliner.reporter.error('invalid RFC number %s' % self.target,
                                              line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]

        return [index, target, reference], []

    def build_uri(self):
        # type: () -> str
        base_url = self.inliner.document.settings.rfc_base_url
        ret = self.target.split('#', 1)
        if len(ret) == 2:
            return base_url + self.inliner.rfc_url % int(ret[0]) + '#' + ret[1]
        else:
            return base_url + self.inliner.rfc_url % int(ret[0])


_amp_re = re.compile(r'(?<!&)&(?![&\s])')


def menusel_role(typ, rawtext, text, lineno, inliner, options={}, content=[]):
    # type: (str, str, str, int, Inliner, Dict, List[str]) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
    warnings.warn('menusel_role() is deprecated. '
                  'Please use MenuSelection or GUILabel class instead.',
                  RemovedInSphinx40Warning, stacklevel=2)
    env = inliner.document.settings.env
    if not typ:
        assert env.temp_data['default_role']
        typ = env.temp_data['default_role'].lower()
    else:
        typ = typ.lower()

    text = utils.unescape(text)
    if typ == 'menuselection':
        text = text.replace('-->', '\N{TRIANGULAR BULLET}')
    spans = _amp_re.split(text)

    node = nodes.inline(rawtext=rawtext)
    for i, span in enumerate(spans):
        span = span.replace('&&', '&')
        if i == 0:
            if len(span) > 0:
                textnode = nodes.Text(span)
                node += textnode
            continue
        accel_node = nodes.inline()
        letter_node = nodes.Text(span[0])
        accel_node += letter_node
        accel_node['classes'].append('accelerator')
        node += accel_node
        textnode = nodes.Text(span[1:])
        node += textnode

    node['classes'].append(typ)
    return [node], []


class GUILabel(SphinxRole):
    amp_re = re.compile(r'(?<!&)&(?![&\s])')

    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]
        node = nodes.inline(rawtext=self.rawtext, classes=[self.name])
        spans = self.amp_re.split(self.text)
        node += nodes.Text(spans.pop(0))
        for span in spans:
            span = span.replace('&&', '&')

            letter = nodes.Text(span[0])
            accelerator = nodes.inline('', '', letter, classes=['accelerator'])
            node += accelerator
            node += nodes.Text(span[1:])

        return [node], []


class MenuSelection(GUILabel):
    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]
        self.text = self.text.replace('-->', '\N{TRIANGULAR BULLET}')  # type: ignore
        return super().run()


_litvar_re = re.compile('{([^}]+)}')
parens_re = re.compile(r'(\\*{|\\*})')


def emph_literal_role(typ, rawtext, text, lineno, inliner,
                      options={}, content=[]):
    # type: (str, str, str, int, Inliner, Dict, List[str]) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
    warnings.warn('emph_literal_role() is deprecated. '
                  'Please use EmphasizedLiteral class instead.',
                  RemovedInSphinx40Warning, stacklevel=2)
    env = inliner.document.settings.env
    if not typ:
        assert env.temp_data['default_role']
        typ = env.temp_data['default_role'].lower()
    else:
        typ = typ.lower()

    retnode = nodes.literal(role=typ.lower(), classes=[typ])
    parts = list(parens_re.split(utils.unescape(text)))
    stack = ['']
    for part in parts:
        matched = parens_re.match(part)
        if matched:
            backslashes = len(part) - 1
            if backslashes % 2 == 1:    # escaped
                stack[-1] += "\\" * int((backslashes - 1) / 2) + part[-1]
            elif part[-1] == '{':       # rparen
                stack[-1] += "\\" * int(backslashes / 2)
                if len(stack) >= 2 and stack[-2] == "{":
                    # nested
                    stack[-1] += "{"
                else:
                    # start emphasis
                    stack.append('{')
                    stack.append('')
            else:                       # lparen
                stack[-1] += "\\" * int(backslashes / 2)
                if len(stack) == 3 and stack[1] == "{" and len(stack[2]) > 0:
                    # emphasized word found
                    if stack[0]:
                        retnode += nodes.Text(stack[0], stack[0])
                    retnode += nodes.emphasis(stack[2], stack[2])
                    stack = ['']
                else:
                    # emphasized word not found; the rparen is not a special symbol
                    stack.append('}')
                    stack = [''.join(stack)]
        else:
            stack[-1] += part
    if ''.join(stack):
        # remaining is treated as Text
        text = ''.join(stack)
        retnode += nodes.Text(text, text)

    return [retnode], []


class EmphasizedLiteral(SphinxRole):
    parens_re = re.compile(r'(\\\\|\\{|\\}|{|})')

    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]
        children = self.parse(self.text)
        node = nodes.literal(self.rawtext, '', *children,
                             role=self.name.lower(), classes=[self.name])

        return [node], []

    def parse(self, text):
        # type: (str) -> List[nodes.Node]
        result = []  # type: List[nodes.Node]

        stack = ['']
        for part in self.parens_re.split(text):
            if part == '\\\\':  # escaped backslash
                stack[-1] += '\\'
            elif part == '{':
                if len(stack) >= 2 and stack[-2] == "{":  # nested
                    stack[-1] += "{"
                else:
                    # start emphasis
                    stack.append('{')
                    stack.append('')
            elif part == '}':
                if len(stack) == 3 and stack[1] == "{" and len(stack[2]) > 0:
                    # emphasized word found
                    if stack[0]:
                        result.append(nodes.Text(stack[0], stack[0]))
                    result.append(nodes.emphasis(stack[2], stack[2]))
                    stack = ['']
                else:
                    # emphasized word not found; the rparen is not a special symbol
                    stack.append('}')
                    stack = [''.join(stack)]
            elif part == '\\{':  # escaped left-brace
                stack[-1] += '{'
            elif part == '\\}':  # escaped right-brace
                stack[-1] += '}'
            else:  # others (containing escaped braces)
                stack[-1] += part

        if ''.join(stack):
            # remaining is treated as Text
            text = ''.join(stack)
            result.append(nodes.Text(text, text))

        return result


_abbr_re = re.compile(r'\((.*)\)$', re.S)


def abbr_role(typ, rawtext, text, lineno, inliner, options={}, content=[]):
    # type: (str, str, str, int, Inliner, Dict, List[str]) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
    warnings.warn('abbr_role() is deprecated.  Please use Abbrevation class instead.',
                  RemovedInSphinx40Warning, stacklevel=2)
    text = utils.unescape(text)
    m = _abbr_re.search(text)
    if m is None:
        return [nodes.abbreviation(text, text, **options)], []
    abbr = text[:m.start()].strip()
    expl = m.group(1)
    options = options.copy()
    options['explanation'] = expl
    return [nodes.abbreviation(abbr, abbr, **options)], []


class Abbreviation(SphinxRole):
    abbr_re = re.compile(r'\((.*)\)$', re.S)

    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]
        matched = self.abbr_re.search(self.text)
        if matched:
            text = self.text[:matched.start()].strip()
            self.options['explanation'] = matched.group(1)
        else:
            text = self.text

        return [nodes.abbreviation(self.rawtext, text, **self.options)], []


def index_role(typ, rawtext, text, lineno, inliner, options={}, content=[]):
    # type: (str, str, str, int, Inliner, Dict, List[str]) -> Tuple[List[nodes.Node], List[nodes.system_message]]  # NOQA
    warnings.warn('index_role() is deprecated.  Please use Index class instead.',
                  RemovedInSphinx40Warning, stacklevel=2)
    # create new reference target
    env = inliner.document.settings.env
    targetid = 'index-%s' % env.new_serialno('index')
    targetnode = nodes.target('', '', ids=[targetid])
    # split text and target in role content
    has_explicit_title, title, target = split_explicit_title(text)
    title = utils.unescape(title)
    target = utils.unescape(target)
    # if an explicit target is given, we can process it as a full entry
    if has_explicit_title:
        entries = process_index_entry(target, targetid)
    # otherwise we just create a "single" entry
    else:
        # but allow giving main entry
        main = ''
        if target.startswith('!'):
            target = target[1:]
            title = title[1:]
            main = 'main'
        entries = [('single', target, targetid, main, None)]
    indexnode = addnodes.index()
    indexnode['entries'] = entries
    set_role_source_info(inliner, lineno, indexnode)
    textnode = nodes.Text(title, title)
    return [indexnode, targetnode, textnode], []


class Index(ReferenceRole):
    def run(self):
        # type: () -> Tuple[List[nodes.Node], List[nodes.system_message]]
        target_id = 'index-%s' % self.env.new_serialno('index')
        if self.has_explicit_title:
            # if an explicit target is given, process it as a full entry
            title = self.title
            entries = process_index_entry(self.target, target_id)
        else:
            # otherwise we just create a single entry
            if self.target.startswith('!'):
                title = self.title[1:]
                entries = [('single', self.target[1:], target_id, 'main', None)]
            else:
                title = self.title
                entries = [('single', self.target, target_id, '', None)]

        index = addnodes.index(entries=entries)
        target = nodes.target('', '', ids=[target_id])
        text = nodes.Text(title, title)
        self.set_source_info(index)
        return [index, target, text], []


specific_docroles = {
    # links to download references
    'download': XRefRole(nodeclass=addnodes.download_reference),
    # links to anything
    'any': AnyXRefRole(warn_dangling=True),

    'pep': PEP(),
    'rfc': RFC(),
    'guilabel': GUILabel(),
    'menuselection': MenuSelection(),
    'file': EmphasizedLiteral(),
    'samp': EmphasizedLiteral(),
    'abbr': Abbreviation(),
    'index': Index(),
}  # type: Dict[str, RoleFunction]


def setup(app):
    # type: (Sphinx) -> Dict[str, Any]
    from docutils.parsers.rst import roles

    for rolename, nodeclass in generic_docroles.items():
        generic = roles.GenericRole(rolename, nodeclass)
        role = roles.CustomRole(rolename, generic, {'classes': [rolename]})
        roles.register_local_role(rolename, role)

    for rolename, func in specific_docroles.items():
        roles.register_local_role(rolename, func)

    return {
        'version': 'builtin',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
