# -*- coding: utf-8 -*-
#
# cli.py
#
# Copyright (c) Nicholas J. Radcliffe 2009-2011 and other authors specified
#               in the AUTHOR
# Licence terms in LICENCE.

import shutil
import sys
import types
from optparse import OptionParser, OptionGroup
from itertools import chain, imap
from fdblib import (
    FluidDB,
    O,
    Credentials,
    get_credentials_file,
    get_typed_tag_value,
    path_style,
    toStr,
    version,
    DEFAULT_ENCODING,
    STATUS,
    DADGAD_ID,
    HTTP_TIMEOUT,
    SANDBOX_PATH,
    FLUIDDB_PATH,
)
import ls


HTTP_METHODS = ['GET', 'PUT', 'POST', 'DELETE', 'HEAD']

ARGLESS_COMMANDS = ['COUNT', 'TAGS', 'LS', 'PWD', 'PWN', 'WHOAMI']

USAGE = u"""

 Tag objects:
   fdb tag -a 'DADGAD' tuning rating=10
   fdb tag -i %s /njr/tuning /njr/rating=10
   fdb tag -q 'about = "DADGAD"' tuning rating=10

 Untag objects:
   fdb untag -a 'DADGAD' /njr/tuning rating
   fdb untag -i %s
   fdb untag -q 'about = "DADGAD"' tuning rating

 Fetch objects and show tags
   fdb show -a 'DADGAD' /njr/tuning /njr/rating
   fdb show -i %s tuning rating
   fdb show -q 'about = "DADGAD"' tuning rating

 Count objects matching query:
   fdb count -q 'has fluiddb/users/username'

 Get tags on objects and their values:
   fdb tags -a 'DADGAD'
   fdb tags -i %s

 Miscellaneous:
   fdb whoami              prints username for authenticated user
   fdb pwd / fdb pwn       prints root namespace of authenticated user
   fdb su fdbuser          set fdb to use user credentials for fdbuser

 Run Tests:
   fdb test                runs all tests
   fdb testcli             tests command line interface only
   fdb testdb              tests core FluidDB interface only
   fdb testutil            runs tests not requiring FluidDB access

 Raw HTTP GET:
   fdb get /tags/njr/google
   fdb get /permissions/tags/njr/rating action=delete
   (use POST/PUT/DELETE/HEAD at your peril; currently untested.)

""" % (DADGAD_ID, DADGAD_ID, DADGAD_ID, DADGAD_ID)


USAGE_FI = u"""

 Tag objects:
   fdb tag -a 'DADGAD' njr/tuning njr/rating=10
   fdb tag -i %s njr/tuning njr/rating=10
   fdb tag -q 'about = "DADGAD"' tuning njr/rating=10

 Untag objects:
   fdb untag -a 'DADGAD' njr/tuning njr/rating
   fdb untag -i %s
   fdb untag -q 'about = "DADGAD"' njr/tuning njr/rating

 Fetch objects and show tags
   fdb show -a 'DADGAD' njr/tuning njr/rating
   fdb show -i %s njr/tuning njr/rating
   fdb show -q 'about = "DADGAD"' njr/tuning njr/rating

 Count objects matching query:
   fdb count -q 'has fluiddb/users/username'

 Get tags on objects and their values:
   fdb tags -a 'DADGAD'
   fdb tags -i %s

 Miscellaneous:
   fdb whoami              prints username for authenticated user
   fdb pwd / fdb pwn       prints root namespace of authenticated user
   fdb su fdbuser          set fdb to use user credentials for fdbuser

 Run Tests:
   fdb test            (runs all tests)
   fdb testcli         (tests command line interface only)
   fdb testdb          (tests core FluidDB interface only)
   fdb testutil        (runs tests not requiring FluidDB access)

 Raw HTTP GET:
   fdb get /tags/njr/google
   fdb get /permissions/tags/njr/rating action=delete
   (use POST/PUT/DELETE/HEAD at your peril; currently untested.)

""" % (DADGAD_ID, DADGAD_ID, DADGAD_ID, DADGAD_ID)


class ModeError(Exception):
    pass


class TooFewArgsForHTTPError(Exception):
    pass


class UnrecognizedHTTPMethodError(Exception):
    pass


class TagValue:
    def __init__(self, name, value=None):
        self.name = name
        self.value = value

    def __unicode__(self):
        return (u'Tag "%s", value "%s" of type %s'
                     % (self.name, toStr(self.value), toStr(type(self.value))))


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
                    print(u'Tagged object %s with %s'
                            % (description,
                               formatted_tag_value(tag.name, tag.value)))
            else:
                warning(u'Failed to tag object %s with %s'
                        % (description, tag.name))
                warning(u'Error code %d' % o)


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
                    print('Removed tag %s from object %s\n'
                          % (tag, description))
            else:
                warning('Failed to remove tag %s from object %s'
                        % (tag, description))
                warning('Error code %d' % o)


def execute_show_command(objs, db, tags, options):
    actions = {
        u'id': db.get_tag_value_by_id,
        u'about': db.get_tag_value_by_about,
    }
    for obj in objs:
        description = describe_by_mode(obj.specifier, obj.mode)
        print u'Object %s:' % description

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
                print u'  %s' % formatted_tag_value(outtag, v)
            elif status == STATUS.NOT_FOUND:
                print u'  %s' % cli_bracket(u'tag %s not present' % outtag)
            else:
                print cli_bracket(u'error code %d getting tag %s' % (status,
                                                                    outtag))


def execute_tags_command(objs, db, options):
    for obj in objs:
        description = describe_by_mode(obj.specifier, obj.mode)
        print u'Object %s:' % description
        id = (db.create_object(obj.specifier).id if obj.mode == u'about'
              else obj.specifier)
        for tag in db.get_object_tags_by_id(id):
            fulltag = u'/%s' % tag
            outtag = u'/%s' % tag if db.unixStyle else tag
            status, v = db.get_tag_value_by_id(id, fulltag)

            if status == STATUS.OK:
                print u'  %s' % formatted_tag_value(outtag, v)
            elif status == STATUS.NOT_FOUND:
                print u'  %s' % cli_bracket(u'tag %s not present' % outtag)
            else:
                print cli_bracket(u'error code %d getting tag %s' % (status,
                                                                    outtag))

def execute_whoami_command(db):
    print db.credentials.username


def execute_su_command(db, args):
    source =  get_credentials_file(username=args[0])
    dest = get_credentials_file()
    shutil.copyfile(source, dest)
    db = FluidDB(Credentials(filename=dest))
    username = db.credentials.username
    file = args[0].decode(DEFAULT_ENCODING)
    extra = u'' if args[0] == username else (u' (file %s)' % file)
    print u'Credentials set to user %s%s.' % (username, extra)

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
    print u'Status: %d' % status
    print u'Result: %s' % toStr(result)


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
    sys.stderr.write(u'%s\n' % msg)


def fail(msg):
    warning(msg)
    sys.exit(1)


def nothing_to_do():
    print u'Nothing to do.'
    sys.exit(0)


def cli_bracket(s):
    return u'(%s)' % s


def get_ids_or_fail(query, db):
    ids = db.query(query)
    if type(ids) == types.IntType:
        fail(u'Query failed')
    else:   # list of ids
        print u'%s matched' % plural(len(ids), u'object')
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
        usage = USAGE_FI if u'-F' in args else USAGE
    else:
        usage = USAGE if u'-U' in args else USAGE_FI
    parser = OptionParser(usage=usage)
    general = OptionGroup(parser, u'General options')
    general.add_option(u'-a', u'--about', action=u'append', default=[],
            help=u'used to specify objects by about tag')
    general.add_option(u'-i', u'--id', action=u'append', default=[],
            help=u'used to specify objects by ID')
    general.add_option(u'-q', u'--query', action=u'append', default=[],
            help=u'used to specify objects with a FluidDB query')
    general.add_option(u'-v', u'--verbose', action=u'store_true', default=False,
            help=u'encourages FDB to report what it\'s doing (verbose mode)')
    general.add_option(u'-D', u'--debug', action=u'store_true', default=False,
            help=u'enables debug mode (more output)')
    general.add_option(u'-T', u'--timeout', type=u'float', default=HTTP_TIMEOUT,
            metavar=u'n', help=u'sets the HTTP timeout to n seconds')
    general.add_option(u'-U', u'--unixstylepaths', action=u'store_true',
                       default=False,
            help=u'Forces unix-style paths for tags and namespaces.')
    general.add_option(u'-u', u'--user', action=u'append', default=[],
            help=u'used to specify a different user (credentials file)')
    general.add_option(u'-F', u'--fluidinfostylepaths', action=u'store_true',
                       default=False,
            help=u'Forces Fluidinfo--style paths for tags and namespaces.')
    general.add_option(u'-V', u'--version', action=u'store_true',
                       default=False,
            help=u'Report version number.')
    general.add_option(u'-R', u'--recurse', action=u'store_true',
                       default=False,
            help=u'recursive (for ls and rm).')
    general.add_option(u'-l', u'--long', action=u'store_true',
                       default=False,
            help=u'long listing (for ls).')
    general.add_option(u'-L', u'--longer', action=u'store_true',
                       default=False,
            help=u'longer listing (for ls).')
    general.add_option(u'-d', u'--namespace', action=u'store_true',
                       default=False,
            help=u'don\'t list namespace; just name of namespace.')

    parser.add_option_group(general)

    other = OptionGroup(parser, u'Other flags')
    other.add_option(u'-s', u'--sandbox', action=u'store_const',
                     dest=u'hostname', const=SANDBOX_PATH,
            help=u'use the sandbox at http://sandbox.fluidinfo.com')
    other.add_option(u'--hostname', default=FLUIDDB_PATH, dest=u'hostname',
            help=(u'use the specified host (which should start http:// or '
                   u'https://; http:// will be added if it doesn\'t) default '
                   u'is %default'))
    parser.add_option_group(other)

    options, args = parser.parse_args(args)

    if args == []:
        action = u'version' if options.version else u'help'
    else:
        action, args = args[0], args[1:]

    return action, args, options, parser


def execute_command_line(action, args, options, parser):
    if not action == u'ls':
        credentials = Credentials(options.user[0]) if options.user else None
        db = FluidDB(host=options.hostname, credentials=credentials,
                     debug=options.debug, unixStylePaths=path_style(options))
    ids_from_queries = chain(*imap(lambda q: get_ids_or_fail(q, db),
        options.query))
    ids = chain(options.id, ids_from_queries)

    objs = [O({u'mode': u'about', u'specifier': a}) for a in options.about] + \
            [O({u'mode': u'id', u'specifier': id}) for id in ids]

    if options.version:
        print u'fdb %s' % version()
        if action == u'version':
            sys.exit(0)
    if action == u'help':
        print USAGE if db.unixStyle else USAGE_FI
        sys.exit(0)
    elif (action.upper() not in HTTP_METHODS + ARGLESS_COMMANDS
          and not args):
        parser.error(u'Too few arguments for action %s' % action)
    elif action == u'count':
        print u'Total: %d objects' % (len(objs))
    elif action == u'tags':
        execute_tags_command(objs, db, options)
    elif action in (u'tag', u'untag', u'show'):
        if not (options.about or options.query or options.id):
            parser.error(u'You must use -q, -a or -i with %s' % action)
        tags = args
        if len(tags) == 0 and action != u'count':
            nothing_to_do()
        actions = {
            u'tag': execute_tag_command,
            u'untag': execute_untag_command,
            u'show': execute_show_command,
        }
        command = actions[action]

        command(objs, db, args, options)
    elif action == u'ls':
        ls.execute_ls_command(objs, args, options)
    elif action in (u'pwd', u'pwn', u'whoami'):
        execute_whoami_command(db)
    elif action == u'su':
        execute_su_command(db, args)
    elif action in ['get', u'put', u'post', u'delete']:
        execute_http_request(action, args, db, options)
    else:
        parser.error(u'Unrecognized command %s' % action)
