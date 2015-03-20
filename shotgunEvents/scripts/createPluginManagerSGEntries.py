#!/usr/bin/env python2.7
"""
:mod:`createPluginManagerSGEntries` -- logger
===================================

.. module:: createPluginManagerSGEntries
   :platform: Unix
   :synopsis: Script to create shotgun entity per plugin for the pluginManager
.. moduleauthor:: Jean-Brice Royer <jbro@mikrosimage.eu>
"""

import os
import re
import sys
import logging
from optparse import OptionParser
from pprint import pprint

import shotgun_api3 as shotgun

from shotgunEventDaemon import Config

def main():
    """
    Main entry
    """
    usage = "Usage: %prog configFile"
    parser = OptionParser(usage=usage)

    (options, args) = parser.parse_args()

    if len(args) < 1:
        print('Missing config file.')
        parser.print_usage()
        return -1

    configFile = args[0]

    if not os.path.exists(configFile):
        print('Given config file does not exist.')
        return -2

    logging.basicConfig(format='%(asctime)s %(message)s',
                        datefmt='%m/%d/%Y-%H:%M:%S',
                        level='INFO')
        
    # Get config
    config = Config(configFile)
    serverURL = config.get('shotgun', 'server')
    customEntity = config.get('pluginManager', 'sgEntity')
    scriptKey = config.get('pluginManager', 'script_key')
    scriptName = config.get('pluginManager', 'script_name')
    isProjectFilteringEnabled = config.getEnableProjectFiltering()

    # Get projects if needed
    sg = shotgun.Shotgun(serverURL, scriptName, scriptKey)
    sgProjects = None
    if isProjectFilteringEnabled:
        sgProjects = sg.find('Project',
                             [['name', 'in', config.getProjectNames()]],
                             ['name'])

    # Get plugin entities
    sgPlugins = sg.find(customEntity,
                        [],
                        ['code',
                         'sg_status_list',
                         'sg_script_path',
                         'sg_ignore_projects'])

    pluginCollectionPaths = config.getPluginPaths()
    for pluginCollectionPath in pluginCollectionPaths:
        for pluginName in os.listdir(pluginCollectionPath):
            if re.search('^\w*.py$', pluginName):
                pluginName = pluginName[:-3]
                pluginPath = "%s.py" % os.path.join(pluginCollectionPath, pluginName)


                # Do not register the pluginManager himself
                if pluginName == "pluginManager":
                    continue

                # Build sg paths
                pluginPaths = {}
                pluginPaths['local_path'] = pluginPath
                pluginPaths['local_path_linux'] = pluginPath
                pluginPaths['url'] = 'file:///%s' % pluginPath
                pluginPaths['local_path'] = pluginPath
                pluginPaths['name'] = os.path.basename(pluginPath)


                # Project filtering enabled
                if sgProjects is not None:
                    for sgProject in sgProjects:

                        # Find plugin entity
                        sgPlugin = None
                        for sgPlugin in sgPlugins:
                            if sgPluginTmp['code'] == pluginName and \
                                    sgPluginTmp['project']['id'] == sgProject['id']:
                                sgPlugin = sgPluginTmp
                                break

                        # Update
                        if sgPlugin is not None:
                            logging.info('Updating plugin '
                                         '%s (id:%d) for project %s' % (pluginName,
                                                                        sgPlugin['id'],
                                                                        sgProject['name']))
                            sg.update(customEntity,
                                      sgPlugin['id'],
                                      {'sg_script_path': pluginPaths,
                                       'project': sgProject})
                        # Create
                        else:
                            logging.info('Creating plugin '
                                         '%s for project %s' % (pluginName,
                                                                sgProject['name']))
                            sg.create(customEntity,
                                      {'code': pluginName,
                                       'sg_script_path': pluginPaths,
                                       'project': sgProject,
                                       'sg_status_list': 'dis'})

                # Project filtering not enabled
                else:

                    # Find plugin entity
                    sgPlugin = None
                    for sgPluginTmp in sgPlugins:
                        if sgPluginTmp['code'] == pluginName:
                            sgPlugin = sgPluginTmp
                            break

                    # Update
                    if sgPlugin is not None:
                        logging.info('Updating plugin '
                                     '%s (id:%d)' % (pluginName,
                                                     sgPlugin['id']))
                        sg.update(customEntity,
                                  sgPlugin['id'],
                                  {'sg_script_path': pluginPaths})
                    # Create
                    else:
                        logging.info('Creating plugin %s' % (pluginName))
                        sg.create(customEntity,
                                  {'code': pluginName,
                                   'sg_script_path': pluginPaths,
                                   'sg_status_list': 'dis'})


if __name__ == '__main__':
    sys.exit(main())
