#!/usr/bin/python

import argparse
import ast
import ConfigParser
import datetime
from collections import deque
import glob
import os.path
import subprocess
import sys
import time

class bcolors:
    FUCHSIA = '\033[95m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    WHITE = '\033[0m'

def printMobMessage(message, end=False):
    if end:
        print bcolors.FUCHSIA + message + bcolors.GREEN + " ====>" + bcolors.WHITE
    else:
        print bcolors.GREEN + "<==== " + bcolors.FUCHSIA + message + bcolors.WHITE

def printMobError(message):
    print >> sys.stderr, bcolors.GREEN + "<==== " + bcolors.RED + "ERROR: " + bcolors.FUCHSIA + message + bcolors.WHITE

class INIParser(ConfigParser.SafeConfigParser):
    def as_dict(self, prefix=''):
        r = {}
        if prefix:
            prefix = prefix + '.'
        for section in self._sections:
            for option in self._sections[section]:
                r[prefix + section + '.' + option] = self._sections[section][option]
            r.pop(prefix + section + '.__name__', None)
        return r

class ConfigFile:
    def __init__(self, name, typeName, defaults):
        self.name = name
        self.typeName = typeName
        self.config = INIParser(defaults)
        self.configFile = os.path.abspath("mobfiles/" + self.name + ".mob" + self.typeName)
        self.parsed = False
        if not os.path.exists(self.configFile):
            printMobError("Could not find the config file `" + self.configFile + "`")
            exit(1)
        else:
            self.parsed = self.config.read(self.configFile)
            if not self.parsed:
                printMobError("Could not parse the config file `" + self.configFile + "`")
                exit(1)
            if self.config.has_section('Main'):
                self.config.set('Main', 'Name', name)

class Device(ConfigFile):
    def __init__(self, name):
        ConfigFile.__init__(self, name, "device", {})

    def architecture(self):
        return self.config.get('Main', 'Architecture') if self.parsed and self.config.has_option('Main', 'Architecture') else ""

    def connectCommand(self):
        return self.config.get('Main', 'ConnectCommand') if self.parsed and self.config.has_option('Main', 'ConnectCommand') else ""

    def disconnectCommand(self):
        return self.config.get('Main', 'DisconnectCommand') if self.parsed and self.config.has_option('Main', 'DisconnectCommand') else ""

class Target:
    def __init__(self, name):
        self.name = name
        self.dependencies = []

class ProjectTarget(ConfigFile, Target):
    def __init__(self, name, arguments, device, parents = None):
        ConfigFile.__init__(self, name, "project", dict(arguments.items() + device.config.as_dict('device').items()))
        Target.__init__(self, name)
        self.device = device
        self.parents = parents
        if self.parents is None:
            self.parents = []

        if self.parsed and self.config.has_option('Main', 'Depends'):
            depends = self.config.get('Main', 'Depends').split()
            for target in depends:
                if target in self.parents:
                    printMobError("Circular dependency detected between `" + self.name + "` and `" + target + "`")
                    exit(1)
                else:
                    self.parents.append(self.name)
                    t = ProjectTarget(target, arguments, self.device, self.parents)
                    if t.parsed:
                        self.dependencies.append(t)
        if self.parsed and self.config.has_option('Main', 'Installs'):
            installs = self.config.get('Main', 'Installs').split()
            for target in installs:
                t = InstallTarget(target, arguments, self.device)
                if t.parsed:
                    self.dependencies.append(t)

    def configureCommand(self):
        return self.config.get('Main', 'ConfigureCommand') if self.parsed and self.config.has_option('Main', 'ConfigureCommand') else ""

    def buildCommand(self):
        return self.config.get('Main', 'BuildCommand') if self.parsed and self.config.has_option('Main', 'BuildCommand') else ""

    def cleanCommand(self):
        return self.config.get('Main', 'CleanCommand') if self.parsed and self.config.has_option('Main', 'CleanCommand') else ""

    def __eq__(self, other):
        return self.name == other.name

class InstallTarget(ConfigFile, Target):
    def __init__(self, name, arguments, device):
        ConfigFile.__init__(self, name, "install", dict(arguments.items() + device.config.as_dict('device').items()))
        Target.__init__(self, name)

    def installCommand(self):
        return self.config.get('Main', 'InstallCommand') if self.parsed and self.config.has_option('Main', 'InstallCommand') else ""

# Resolve project dependencies
def resolveDependencies(target, resolved):
    for dependency in target.dependencies:
        if dependency not in resolved:
            resolveDependencies(dependency, resolved)
    resolved.append(target)

# Get all the mobfiles
paths = ['./mobfiles']
if 'MOBFILES' in os.environ:
    paths = paths + os.environ['MOBFILES'].split(':')

possibleDevices = []
possibleProjects = []
possibleInstalls = []

for path in paths:
    for name in glob.glob(path + '/*.mobdevice'):
        f = os.path.splitext(os.path.basename(name))[0]
        if not f in possibleDevices:
            possibleDevices.append(f)

    for name in glob.glob(path + '/*.mobproject'):
        f = os.path.splitext(os.path.basename(name))[0]
        if not f in possibleProjects:
            possibleProjects.append(f)

    for name in glob.glob(path + '/*.mobinstall'):
        f = os.path.splitext(os.path.basename(name))[0]
        if not f in possibleInstalls:
            possibleInstalls.append(f)

# Argument parsing
parser = argparse.ArgumentParser(prog='mob', description='Mob is a system builder and installer.')
subparsers = parser.add_subparsers(title='commands', dest='command', help="see \'mob <command> --help\' for more information")
parser_build = subparsers.add_parser('build', help='builds the specified target(s)', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser_install = subparsers.add_parser('install', help='installs the specified target(s)', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser_device = subparsers.add_parser('device', help='commands for the specified device', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

# Options for building
parser_build.add_argument('--time', dest='time', action='store_true', help='displays elapsed time for each command')
parser_build.add_argument('--quiet', dest='quiet', action='store_true', help='turns off command output')
parser_build.add_argument('--no-deps', dest='nodeps', action='store_true', help='turns off dependency checking')
parser_build.add_argument('--no-config', dest='noconfig', action='store_true', help='turns off the configure step')
parser_build.add_argument('--clean', dest='clean', action='store_true', help='specifies a clean build')
parser_build.add_argument('--type', dest='type', choices=['debug','release'], default='release', help='specifies the type of build')
parser_build.add_argument('--args', dest='args', metavar='\"{key: value, key: value, ...}\"', help='dictionary of arguments to pass along to the target(s)')
parser_build.add_argument('device', nargs=1, choices=possibleDevices, help='the device target')
parser_build.add_argument('targets', nargs='+', choices=possibleProjects, help='one or more build target(s)')

# Options for installing
parser_install.add_argument('--time', dest='time', action='store_true', help='displays elapsed time for each command')
parser_install.add_argument('--quiet', dest='quiet', action='store_true', help='turns off command output')
parser_install.add_argument('--no-deps', dest='nodeps', action='store_true', help='turns off dependency checking')
parser_install.add_argument('--type', dest='type', choices=['debug','release'], default='release', help='specifies the type of build')
parser_install.add_argument('--args', dest='args', metavar='\"{key: value, key: value, ...}\"', help='dictionary of arguments to pass along to the target(s)')
parser_install.add_argument('device', nargs=1, choices=possibleDevices, help='the device target')
parser_install.add_argument('targets', nargs='+', choices=possibleProjects + possibleInstalls, help='one or more install target(s)')

# Options for device
parser_device.add_argument('--time', dest='time', action='store_true', help='displays elapsed time for each command')
parser_device.add_argument('--quiet', dest='quiet', action='store_true', help='turns off command output')
connectGroup = parser_device.add_mutually_exclusive_group(required=True)
connectGroup.add_argument('--connect', action='store_true', help='connects the specified device')
connectGroup.add_argument('--disconnect', action='store_true', help='disconnects the specified device')
parser_device.add_argument('device', nargs=1, choices=possibleDevices, help='the device target')

args = parser.parse_args()

# Process a command by evaluating it in a shell
def processCommand(command):
    print command
    syms = deque(['-\\', '-|', '-/', '--'])
    if args.time:
        start = datetime.datetime.now()
    if args.quiet:
        FNULL = open(os.devnull, "w")
        sys.stdout.write("Processing:  ")
        popen = subprocess.Popen(command, stdin=FNULL, stdout=FNULL, stderr=FNULL, shell=True)
        spinner = datetime.datetime.now()
        out = bcolors.GREEN + "\b%s"
        while popen.poll() == None:
            if (datetime.datetime.now() - spinner).total_seconds() >= 0.05:
                sym = syms.popleft()
                sys.stdout.write(out % sym)
                sys.stdout.flush()
                syms.append(sym)
                spinner = datetime.datetime.now()
        sys.stdout.write(bcolors.GREEN + "\b->" + bcolors.WHITE + " done!" + " \n")
        sys.stdout.flush()
    else:
        popen = subprocess.Popen(command, shell=True)
        popen.wait()

    if popen.returncode:
        printMobError("the command returned exit code " + str(popen.returncode) + "!")
        exit(1)

    if args.time:
        printMobMessage("Took " + str("%.2f" % (datetime.datetime.now() - start).total_seconds()) + " seconds", True)
        print ""

# Setup the device
device = Device(args.device[0]);

# Start processing the args
if args.command == 'build' or args.command == 'install':
    target_arguments = {}
    if args.command == 'build':
        target_arguments = {'Main.BuildType':args.type}
    try:
        if args.args:
            target_arguments = ast.literal_eval(args.args)
    except (ValueError, SyntaxError):
        printMobError("Could not parse target arguments `" + args.args + "`")
        printMobError("The arguments must be in the form of a valid python dictionary data type!")
        exit(1)

    root = Target('root')
    for target in args.targets:
        if target in possibleProjects:
            t = ProjectTarget(target, target_arguments, device)
        elif target in possibleInstalls:
            t = InstallTarget(target, target_arguments, device)
        if t.parsed:
            root.dependencies.append(t)

    targetList = []
    if args.nodeps:
        targetList = root.dependencies
    else:
        resolveDependencies(root, targetList)

    for target in targetList:
        if isinstance(target, ProjectTarget):
            if args.command == 'build':
                if args.clean and target.buildCommand():
                    printMobMessage("Cleaning " + target.name + " for " + device.name + "...")
                    processCommand(target.cleanCommand())
                if not args.noconfig and target.configureCommand():
                    printMobMessage("Configuring " + target.name + " for " + device.name + "...")
                    processCommand(target.configureCommand())
                if target.buildCommand():
                    printMobMessage("Building " + target.name + " for " + device.name + "...")
                    processCommand(target.buildCommand())
        elif isinstance(target, InstallTarget):
            if args.command == 'install':
                printMobMessage("Installing " + target.name + " onto " + device.name + "... ")
                processCommand(target.installCommand())

elif args.command == 'device':
    if args.connect and device.connectCommand():
        printMobMessage("Connecting to " + device.name + "...")
        processCommand(device.connectCommand())
    elif args.disconnect and device.disconnectCommand():
        printMobMessage("Disconnecting from " + device.name + "...")
        processCommand(device.disconnectCommand())
