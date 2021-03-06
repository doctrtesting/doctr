"""
doctr

A tool to automatically deploy docs to GitHub pages from Travis CI.

The doctr command is two commands in one. To use, first run

doctr configure

on your local machine. This will prompt for your GitHub credentials and the
name of the repo you want to deploy docs for. This will generate a secure key,
which you should insert into your .travis.yml.

Then, on Travis, for the build where you build your docs, add

    - doctr deploy

to the end of the build to deploy the docs to GitHub pages.  This will only
run on the master branch, and won't run on pull requests.

For more information, see https://gforsyth.github.io/doctr/docs/
"""

import sys
import os
import argparse

from textwrap import dedent

from .local import (generate_GitHub_token, encrypt_variable, encrypt_file,
    upload_GitHub_deploy_key, generate_ssh_key)
from .travis import setup_GitHub_push, commit_docs, push_docs, get_current_repo
from . import __version__

def get_parser():
    # This uses RawTextHelpFormatter so that the description (the docstring of
    # this module) is formatted correctly. Unfortunately, that means that
    # parser help is not text wrapped (but all other help is).
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter, epilog="""
Run --help on the subcommands like 'doctr deploy --help' to see the
options available.
        """,
        )
    parser.add_argument('-V', '--version', action='version', version='doctr ' + __version__)

    subcommand = parser.add_subparsers(title='subcommand', dest='subcommand')
    deploy_parser = subcommand.add_parser('deploy', help=""""Deploy the docs to GitHub from Travis.""")
    deploy_parser.set_defaults(func=deploy)
    deploy_parser.add_argument('--force', action='store_true', help="""Run the deploy command even
    if we do not appear to be on Travis.""")
    deploy_parser.add_argument('--token', action='store_true', default=False,
        help="""Push to GitHub using a personal access token. Use this if you
        used 'doctr configure --token'.""")
    deploy_parser.add_argument('--key-path', default='github_deploy_key.enc',
        help="""Path of the encrypted GitHub deploy key. The default is %(default)r.""")
    deploy_parser.add_argument('--built-docs', default='docs/_build/html',
        help="""Location of the built html documentation to be deployed to
        gh-pages. The default is %(default)r.""")
    deploy_parser.add_argument('--gh-pages-docs', default='docs',
        help="""Directory to deploy the html documentation to on gh-pages. The
        default is %(default)r.""")
    deploy_parser.add_argument('--tmp-dir', default='_docs',
        help="""Temporary directory used on gh-pages. The default is %(default)r.""")
    deploy_parser.add_argument('--deploy-repo', default=None, help="""Repo to
        deploy the docs to. By default, it deploys to the repo Doctr is run from.""")


    configure_parser = subcommand.add_parser('configure', help="Configure doctr. This command should be run locally (not on Travis).")
    configure_parser.set_defaults(func=configure)
    configure_parser.add_argument('--force', action='store_true', help="""Run the configure command even
    if we appear to be on Travis.""")
    configure_parser.add_argument('--token', action="store_true", default=False,
        help="""Generate a personal access token to push to GitHub. The default is to use a
        deploy key. WARNING: This will grant read/write access to all the
        public repositories for the user. This option is not recommended
        unless you are using a separate GitHub user for deploying.""")
    configure_parser.add_argument("--no-upload-key", action="store_false", default=True,
        dest="upload_key", help="""Don't automatically upload the deploy key
        to GitHub.""")
    configure_parser.add_argument('--key-path', default='github_deploy_key',
        help="""Path to save the encrypted GitHub deploy key. The default is %(default)r.
    The .enc extension is added to the file automatically.""")

    return parser

def process_args(parser):
    args = parser.parse_args()

    if not args.subcommand:
        parser.print_usage()
        parser.exit(1)

    return args.func(args, parser)

def on_travis():
    return os.environ.get("TRAVIS_JOB_NUMBER", '')

def deploy(args, parser):
    if not args.force and not on_travis():
        parser.error("doctr does not appear to be running on Travis. Use "
            "doctr deploy --force to run anyway.")

    build_repo = get_current_repo()
    deploy_repo = args.deploy_repo or build_repo

    if setup_GitHub_push(deploy_repo, auth_type='token' if args.token else
        'deploy_key', full_key_path=args.key_path):
        commit_docs(built_docs=args.built_docs,
            gh_pages_docs=args.gh_pages_docs, tmp_dir=args.tmp_dir)
        push_docs()

class IncrementingInt:
    def __init__(self, i=0):
        self.i = i

    def __repr__(self):
        ret = repr(self.i)
        self.i += 1
        return ret

    __str__ = __repr__

def configure(args, parser):
    if not args.force and on_travis():
        parser.error("doctr appears to be running on Travis. Use "
            "doctr configure --force to run anyway.")

    build_repo = input("What repo do you want to build the docs for (org/reponame, like 'gforsyth/doctr')? ")
    deploy_repo = input("What repo do you want to deploy the docs to? [{build_repo}]".format(build_repo=build_repo))

    if not deploy_repo:
        deploy_repo = build_repo

    N = IncrementingInt(1)

    if args.token:
        token = generate_GitHub_token()
        encrypted_variable = encrypt_variable("GH_TOKEN={token}".format(token=token).encode('utf-8'),
            build_repo=build_repo)
        print(dedent("""
        A personal access token for doctr has been created.

        You can go to https://github.com/settings/tokens to revoke it."""))

        print("\n============ You should now do the following ============\n")
    else:
        ssh_key = generate_ssh_key("doctr deploy key for {deploy_repo}".format(deploy_repo=deploy_repo), keypath=args.key_path)
        key = encrypt_file(args.key_path, delete=True)
        encrypted_variable = encrypt_variable(b"DOCTR_DEPLOY_ENCRYPTION_KEY=" + key, build_repo=build_repo)

        deploy_keys_url = 'https://github.com/{deploy_repo}/settings/keys'.format(deploy_repo=deploy_repo)

        if args.upload_key:

            upload_GitHub_deploy_key(deploy_repo, ssh_key)

            print(dedent("""
            The deploy key has been added for {deploy_repo}.

            You can go to {deploy_keys_url} to revoke the deploy key.\
            """.format(deploy_repo=deploy_repo, deploy_keys_url=deploy_keys_url, keypath=args.key_path)))
            print("\n============ You should now do the following ============\n")
        else:
            print("\n============ You should now do the following ============\n")
            print(dedent("""\
            {N}. Go to {deploy_keys_url} and add the following as a new key:

            {ssh_key}
            Be sure to allow write access for the key.
            """.format(ssh_key=ssh_key, deploy_keys_url=deploy_keys_url, N=N)))

        # TODO: Should we just delete the public key?

        print(dedent("""\
        {N}. Commit the file {keypath}.enc. The file {keypath}.pub contains the
        public deploy key for GitHub. It does not need to be
        committed.
        """.format(keypath=args.key_path, N=N)))

    options = ''
    if args.key_path != 'github_deploy_key':
        options += ' --key-path {keypath}.enc'.format(keypath=args.key_path)
    if deploy_repo != build_repo:
        options += ' --deploy-repo {deploy_repo}'.format(deploy_repo=deploy_repo)

    print(dedent("""\
    {N}. Add

        - pip install doctr
        - doctr deploy {options}

    to the docs build of your .travis.yml.
    """.format(options=options, N=N)))

    print(dedent("""\
    {N}. Put

        env:
          global:
            - secure: "{encrypted_variable}"

    in your .travis.yml.
    """.format(encrypted_variable=encrypted_variable.decode('utf-8'), N=N)))

def main():
    return process_args(get_parser())

if __name__ == '__main__':
    sys.exit(main())
