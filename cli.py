# -*- coding: utf-8 -*-
#
# cli.py
#
# Copyright (c) Nicholas J. Radcliffe 2009-2011 and other authors specified
#               in the AUTHOR
# Licence terms in LICENCE.

import os
import shutil
import sys
import types
from optparse import OptionParser, OptionGroup
from itertools import chain, imap
from fishlib import (
    FluidDB,
    O,
    Credentials,
    get_credentials_file,
    get_typed_tag_value,
    path_style,
    Print,
    toStr,
    uprint,
    version,
    DEFAULT_ENCODING,
    STATUS,
    DADGAD_ID,
    PARIS_ID,
    HTTP_TIMEOUT,
    SANDBOX_PATH,
    FLUIDDB_PATH,
)
import ls
import flags
import abouttag.amazon


HTTP_METHODS = ['GET', 'PUT', 'POST', 'DELETE', 'HEAD']

ARGLESS_COMMANDS = ['COUNT', 'TAGS', 'LS', 'PWD', 'PWN', 'WHOAMI']

USAGE = u'''

For help with a specific command, type help followed by the command name.
For a list of commands, type commands.

 Tag objects:
   tag -a 'Paris' visited rating=10
   tag -i %s /njr/visited /njr/rating=10
   tag -q 'about = "Paris"' visited rating=10
   [On windows: tag -q "about = "Paris""" visited rating=10

 Untag objects:
   untag -a 'Paris' /njr/visited rating
   untag -i %s
   untag -q 'about = "Paris"' visited rating

 Fetch objects and show tags
   show -a 'Paris' /njr/visited /njr/rating
   show -i %s visited rating
   show -q 'about = "Paris"' visited rating

 Count objects matching query:
   count -q 'has fluiddb/users/username'

 Get tags on objects and their values:
   tags -a 'Paris'
   tags -i %s

 Tag and Namespace management:
   ls [flags]          list the contents of a namespace or list a tag
   perms spec paths    change the permissions on tags or namespaces
   rm [flags] paths    remove one or more namespaces or tags
   touch [flags] path  create an (abstract) tag (normally unnecessary)
   mkns [flags] path   create a namespace (normally unnecessary)
   pwd / pwn           prints root namespace of authenticated user

 Miscellaneous:
   whoami              prints username for authenticated user
   su fiuser           set fish to use user credentials for fiuser
   help [command]      show this help, or help for the nominated comamnd.
   commands            show a list of available commands
   amazon 'url'        show the about tag for a book on ana Amazon US/UK page

 Run Tests:
   test                runs all tests
   testcli             tests command line interface only
   testdb              tests core FluidDB interface only
   testutil            runs tests not requiring FluidDB access


''' % (PARIS_ID, PARIS_ID, PARIS_ID, PARIS_ID)


USAGE_FI = u'''

For help with a specific command, type help followed by the command name.
For a list of commands, type commands.

 Tag objects:
   tag -a 'Paris' njr/visited njr/rating=10
   tag -i %s njr/visited njr/rating=10
   tag -q 'about = "Paris"' njr/visited njr/rating=10
   [On windows: tag -q "about = "Paris""" njr/visited njr/rating=10

 Untag objects:
   untag -a 'Paris' njr/visited njr/rating
   untag -i %s
   untag -q 'about = "Paris"' njr/visited njr/rating

 Fetch objects and show tags
   show -a 'Paris' njr/visited njr/rating
   show -i %s njr/visited njr/rating
   show -q 'about = "Paris"' njr/visited njr/rating

 Count objects matching query:
   count -q 'has fluiddb/users/username'

 Get tags on objects and their values:
   tags -a 'Paris'
   tags -i %s

 Tag and Namespace management:
   ls [flags]          list the contents of a namespace or list a tag
   perms spec paths    change the permissions on tags or namespaces
   rm [flags] paths    remove one or more namespaces or tags
   touch [flags] path  create an (abstract) tag (normally unnecessary)
   mkns [flags] path   create a namespace (normally unnecessary)
   pwd / pwn           prints root namespace of authenticated user

 Miscellaneous:
   whoami              prints username for authenticated user
   pwd / pwn           prints root namespace of authenticated user
   su fiuser           set fish to use user credentials for fiuser
   help [command]      show this help, or help for the nominated comamnd.
   commands            show a list of available commands
   amazon 'url'        show the about tag for a book on ana Amazon US/UK page

 Run Tests:
   test            (runs all tests)
   testcli         (tests command line interface only)
   testdb          (tests core FluidDB interface only)
   testutil        (runs tests not requiring FluidDB access)

 Raw HTTP GET:
   get /tags/njr/google
   get /permissions/tags/njr/rating action=delete
   (use POST/PUT/DELETE/HEAD at your peril; currently untested.)

''' % (PARIS_ID, PARIS_ID, PARIS_ID, PARIS_ID)


class ModeError(Exception):
    pass


class TooFewArgsForHTTPError(Exception):
    pass


class UnrecognizedHTTPMethodError(Exception):
    pass


class CommandError(Exception):
    pass


class TagValue:
    def __init__(self, name, value=None):
        self.name = name
        self.value = value

    def __unicode__(self):
        return (u'Tag "%s", value "%s" of type %s'
                     % (self.name, toStr(self.value), toStr(type(self.value))))


def error_code(n):
    code = STATUS.__dict__
    for key in code:
        if n == code[key]:
            return unicode('%d (%s)' % (n, key.replace('_', ' ')))
    return unicode(n)


def execute_tag_command(objs, db, tags, options):
    tags = form_tag_value_pairs(tags)
    actions = {
        u'id': db.tag_object_by_id,
        u'about': db.tag_object_by_about,
    }
    for obj in objs:
        description = describe_by_mode(obj.specifier, obj.mode)
        for tag in tags:
            o = actions[obj.mode](obj.specifier, tag.name, tag.value,
                                  inPref=True)
            if o == 0:
                if options.verbose:
                    Print(u'Tagged object %s with %s'
                            % (description,
                               formatted_tag_value(tag.name, tag.value)))
            else:
                warning(u'Failed to tag object %s with %s'
                        % (description, tag.name))
                warning(u'Error code %s' % error_code(o))


def execute_untag_command(objs, db, tags, options):
    actions = {
        'id': db.untag_object_by_id,
        'about': db.untag_object_by_about,
    }
    for obj in objs:
        description = describe_by_mode(obj.specifier, obj.mode)
        for tag in tags:
            o = actions[obj.mode](obj.specifier, tag, inPref=True)
            if o == 0:
                if options.verbose:
                    Print('Removed tag %s from object %s\n'
                          % (tag, description))
            else:
                warning(u'Failed to remove tag %s from object %s'
                        % (tag, description))
                warning(u'Error code %s' % error_code(o))


def execute_show_command(objs, db, tags, options):
    actions = {
        u'id': db.get_tag_value_by_id,
        u'about': db.get_tag_value_by_about,
    }
    for obj in objs:
        description = describe_by_mode(obj.specifier, obj.mode)
        Print(u'Object %s:' % description)

        for tag in tags:
            fulltag = db.abs_tag_path(tag, inPref=True)
            outtag = db.abs_tag_path(tag, inPref=True, outPref=True)
            if tag == u'/id':
                if obj.mode == u'about':
                    o = db.query(u'fluiddb/about = "%s"' % obj.specifier)
                    if type(o) == types.IntType:  # error
                        status, v = o, None
                    else:
                        status, v = STATUS.OK, o[0]
                else:
                    status, v = STATUS.OK, obj.specifier
            else:
                status, v = actions[obj.mode](obj.specifier, tag, inPref=True)

            if status == STATUS.OK:
                Print(u'  %s' % formatted_tag_value(outtag, v))
            elif status == STATUS.NOT_FOUND:
                Print(u'  %s' % cli_bracket(u'tag %s not present' % outtag))
            else:
                Print(cli_bracket(u'error code %s attempting to read tag %s'
                                  % (error_code(status), outtag)))


def execute_tags_command(objs, db, options):
    for obj in objs:
        description = describe_by_mode(obj.specifier, obj.mode)
        Print(u'Object %s:' % description)
        id = (db.create_object(obj.specifier).id if obj.mode == u'about'
              else obj.specifier)
        for tag in db.get_object_tags_by_id(id):
            fulltag = u'/%s' % tag
            outtag = u'/%s' % tag if db.unixStyle else tag
            status, v = db.get_tag_value_by_id(id, fulltag)

            if status == STATUS.OK:
                Print(u'  %s' % formatted_tag_value(outtag, v))
            elif status == STATUS.NOT_FOUND:
                Print(u'  %s' % cli_bracket(u'tag %s not present' % outtag))
            else:
                Print(cli_bracket(u'error code %s attempting to read tag %s'
                                  % (error_code(status), uttag)))


def execute_whoami_command(db):
    Print(db.credentials.username)


def execute_touch_command(db, args, options):
    for tag in args:
        fullpath = db.abs_tag_path(tag, inPref=True)
        if not db.tag_exists(fullpath):
            id = db.create_abstract_tag(fullpath,
                                        description=options.description,
                                        verbose=True)
                

def execute_mkns_command(db, args, options):
    for ns in args:
        fullpath = db.abs_tag_path(ns, inPref=True)
        if not db.ns_exists(fullpath):
            id = db.create_namespace(fullpath,
                                     description=options.description,
                                     verbose=True)


def execute_su_command(db, args):
    source =  get_credentials_file(username=args[0])
    dest = get_credentials_file()
    shutil.copyfile(source, dest)
    db = FluidDB(Credentials(filename=dest))
    username = db.credentials.username
    file = args[0].decode(DEFAULT_ENCODING)
    extra = u'' if args[0] == username else (u' (file %s)' % file)
    Print(u'Credentials set to user %s%s.' % (username, extra))


def execute_amazon_command(db, args):
    Print(abouttag.amazon.get_about_tag_for_item(args[0]))


def execute_http_request(action, args, db, options):
    """Executes a raw HTTP command (GET, PUT, POST, DELETE or HEAD)
       as specified on the command line."""
    method = action.upper()
    if method not in HTTP_METHODS:
        raise UnrecognizedHTTPMethodError(u'Only supported HTTP methods are'
                u'%s and %s' % (' '.join(HTTP_METHODS[:-1], HTTP_METHODS[-1])))

    if len(args) == 0:
        raise TooFewArgsForHTTPError(u'HTTP command %s requires a URI'
                                     % method)
    uri = args[0]
    tags = form_tag_value_pairs(args[1:])
    if method == u'PUT':
        body = {tags[0].tag: tags[0].value}
        tags = tags[1:]
    else:
        body = None
    hash = {}
    for pair in tags:
        hash[pair.name] = pair.value
    status, result = db.call(method, uri, body, hash)
    Print(u'Status: %d' % status)
    Print(u'Result: %s' % toStr(result))


def describe_by_mode(specifier, mode):
    """mode can be a string (about, id or query) or a flags object
        with flags.about, flags.query and flags.id"""
    if mode == u'about':
        return describe_by_about(specifier)
    elif mode == u'id':
        return describe_by_id(specifier)
    elif mode == u'query':
        return describe_by_id(specifier)
    raise ModeError(u'Bad Mode')


def describe_by_about(specifier):
    return u'with about="%s"' % specifier


def describe_by_id(specifier):
    return specifier


def formatted_tag_value(tag, value):
    if value == None:
        return tag
    elif type(value) in types.StringTypes:
        return u'%s = "%s"' % (tag, value)
    else:
        return u'%s = %s' % (tag, toStr(value))


def form_tag_value_pairs(tags):
    pairs = []
    for tag in tags:
        eqPos = tag.find('=')
        if eqPos == -1:
            pairs.append(TagValue(tag, None))
        else:
            t = tag[:eqPos]
            v = get_typed_tag_value(tag[eqPos + 1:])
            pairs.append(TagValue(t, v))
    return pairs


def warning(msg):
#    sys.stderr.write(u'%s\n' % msg)
    Print(u'%s\n' % msg)


def fail(msg):
    warning(msg)
    raise Exception, msg


def nothing_to_do():
    Print(u'Nothing to do.')
    raise Exception, msg


def cli_bracket(s):
    return u'(%s)' % s


def get_ids_or_fail(query, db):
    ids = db.query(query)
    if type(ids) == int:
        raise CommandError(ids, 'Probably a bad query specification')
    else:
        Print(u'%s matched' % plural(len(ids), u'object'))
        return ids


def plural(n, s, pl=None, str=False, justTheWord=False):
    """Returns a string like '23 fields' or '1 field' where the
        number is n, the stem is s and the plural is either stem + 's'
        or stem + pl (if provided)."""
    smallints = [u'zero', u'one', u'two', u'three', u'four', u'five',
                 u'six', u'seven', u'eight', u'nine', u'ten']

    if pl == None:
        pl = u's'
    if str and n < 10 and n >= 0:
        strNum = smallints[n]
    else:
        strNum = int(n)
    if n == 1:
        if justTheWord:
            return s
        else:
            return (u'%s %s' % (strNum, s))
    else:
        if justTheWord:
            return u'%s%s' % (s, pl)
        else:
            return (u'%s %s%s' % (strNum, s, pl))


def parse_args(args=None):
    if args is None:
        args = [a.decode(DEFAULT_ENCODING) for a in sys.argv[1:]]
        if Credentials().unixStyle:
            usage = USAGE_FI if '-F' in args else USAGE
        else:
            usage = USAGE if '-U' in args else USAGE_FI
    else:
        usage = USAGE_FI
    parser = OptionParser(usage=usage)
    general = OptionGroup(parser, 'General options')
    general.add_option('-a', '--about', action='append', default=[],
            help='used to specify objects by about tag')
    general.add_option('-i', '--id', action='append', default=[],
            help='used to specify objects by ID')
    general.add_option('-q', '--query', action='append', default=[],
            help='used to specify objects with a FluidDB query')
    general.add_option('-v', '--verbose', action='store_true', default=False,
            help='encourages FDB to report what it\'s doing (verbose mode)')
    general.add_option('-D', '--debug', action='store_true', default=False,
            help='enables debug mode (more output)')
    general.add_option('-T', '--timeout', type='float', default=HTTP_TIMEOUT,
            metavar='n', help='sets the HTTP timeout to n seconds')
    general.add_option('-U', '--unixstylepaths', action='store_true',
                       default=False,
            help='Forces unix-style paths for tags and namespaces.')
    general.add_option('-u', '--user', action='append', default=[],
            help='used to specify a different user (credentials file)')
    general.add_option('-F', '--fluidinfostylepaths', action='store_true',
                       default=False,
            help='Forces Fluidinfo--style paths for tags and namespaces.')
    general.add_option('-V', '--version', action='store_true',
                       default=False,
            help='Report version number.')
    general.add_option('-R', '--Recurse', action='store_true',
                       default=False,
            help='recursive (for ls).')
    general.add_option('-r', '--recurse', action='store_true',
                       default=False,
            help='recursive (for rm).')
    general.add_option('-f', '--force', action='store_true',
                       default=False,
            help='force (override pettifogging objections).')
    general.add_option('-l', '--long', action='store_true',
                       default=False,
            help='long listing (for ls).')
    general.add_option('-L', '--longer', action='store_true',
                       default=False,
            help='longer listing (for ls).')
    general.add_option('-g', '--group', action='store_true',
                       default=False,
            help='long listing with groups (for ls).')
    general.add_option('-d', '--namespace', action='store_true',
                       default=False,
            help='don\'t list namespace; just name of namespace.')
    general.add_option('-P', '--policy', action='store_true',
                       default=False,
            help='policy (i.e. default permission).')
    general.add_option('-n', '--ns', action='store_true',
                       default=False,
            help='don\'t list namespace; just name of namespace.')
    general.add_option('-m', '--description', action='store_true',
                       default=False,
            help='set description ("metadata") for tag/namespace.')
    general.add_option('-2', '--hightestverbosity', action='store_true',
                       default=False,
            help='don\'t list namespace; just name of namespace.')
    parser.add_option_group(general)

    other = OptionGroup(parser, 'Other flags')
    other.add_option('-s', '--sandbox', action='store_const',
                     dest='hostname', const=SANDBOX_PATH,
            help='use the sandbox at http://sandbox.fluidinfo.com')
    other.add_option('--hostname', default=FLUIDDB_PATH, dest='hostname',
            help=('use the specified host (which should start http:// or '
                   'https://; http:// will be added if it doesn\'t) default '
                   'is %default'))
    parser.add_option_group(other)

    options, args = parser.parse_args(args)
    if options.Recurse:
        options.recurse = options.Recurse

    if args == []:
        action = 'version' if options.version else 'help'
    else:
        action, args = args[0], args[1:]

    return action, args, options, parser


def execute_command_line(action, args, options, parser, user=None, pwd=None,
                         unixPaths=None, docbase=None):
    credentials = (Credentials(user or options.user[0], pwd)
                   if (user or options.user) else None)
    if not action == 'ls':
        unixPaths = (path_style(options) if path_style(options) is not None
                                         else unixPaths)
        db = FluidDB(host=options.hostname, credentials=credentials,
                     debug=options.debug, unixStylePaths=unixPaths)
    ids_from_queries = chain(*imap(lambda q: get_ids_or_fail(q, db),
        options.query))
    ids = chain(options.id, ids_from_queries)

    command_list = [
        'help',
        'version',
        'commands',
        'tag',
        'untag',
        'show',
        'tags',
        'count',
        'ls',
        'rm',
        'perms',
        'pwd',
        'pwn',
        'rmdir',
        'rmns',
        'touch',
        'mkns',
        'mkdir',
        'amazon',
        'test',
        'testcli',
        'testdb',
        'testapi',
        'whoami',
        'su',
    ]

    objs = [O({'mode': 'about', 'specifier': a}) for a in options.about] + \
            [O({'mode': 'id', 'specifier': id}) for id in ids]

    if action == 'version' or options.version:
        Print('fish %s' % version())
        if action == 'version':
            return
    
    try:
        if action == 'help':
            if args and args[0] in command_list:
                base = docbase or sys.path[0]
                f = open(os.path.join(base, 'doc/build/text/%s.txt' % args[0]))
                Print (f.read())
                f.close()
            else:
                Print(USAGE if db.unixStyle else USAGE_FI)
        elif action == 'commands':
            Print(' '.join(command_list))
        elif action not in command_list:
            Print('Unrecognized command %s' % action)        
        elif (action.upper() not in HTTP_METHODS + ARGLESS_COMMANDS
              and not args):
            Print('Too few arguments for action %s' % action)
        elif action == 'count':
            Print('Total: %s' % (flags.Plural(len(objs), 'object')))
        elif action == 'tags':
            execute_tags_command(objs, db, options)
        elif action in ('tag', 'untag', 'show'):
            if not (options.about or options.query or options.id):
                Print('You must use -q, -a or -i with %s' % action)
                return
            tags = args
            if len(tags) == 0 and action != 'count':
                nothing_to_do()
            actions = {
                'tag': execute_tag_command,
                'untag': execute_untag_command,
                'show': execute_show_command,
            }
            command = actions[action]
            command(objs, db, args, options)
        elif action == 'ls':
            ls.execute_ls_command(objs, args, options, credentials, unixPaths)
        elif action == 'rm':
            ls.execute_rm_command(objs, args, options, credentials, unixPaths)
        elif action in ('rmdir', 'rmns'):
            raise CommandError(u'Use rm to remove namespaces as well as tags')
        elif action == 'chmod':
            ls.execute_chmod_command(objs, args, options, credentials,
                                     unixPaths)
        elif action == 'perms':
            ls.execute_perms_command(objs, args, options, credentials,
                                     unixPaths)
        elif action in ('pwd', 'pwn', 'whoami'):
            execute_whoami_command(db)
        elif action == 'touch':
            execute_touch_command(db, args, options)
        elif action in ('mkns', 'mkdir'):
            execute_mkns_command(db, args, options)
        elif action == 'su':
            execute_su_command(db, args)
        elif action == 'amazon':
            execute_amazon_command(db, args)
        elif action in ['get', 'put', 'post', 'delete']:
            execute_http_request(action, args, db, options)
        else:
            Print('Unrecognized command %s' % action)
    except Exception, e:
        if options.debug:
            raise
        else:
            Print('Fish failure:\n  %s' % e)

