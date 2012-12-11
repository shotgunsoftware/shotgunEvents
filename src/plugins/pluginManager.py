"""
For detailed information about the event loop, please see

http://shotgunsoftware.github.com/shotgunEvents/api.html

This plugin allows to control plugins from Shotgun. 
To use it :
- Enable a Custom Non Project Entity in Shotgun, rename it to Plugins ( or whatever name you fancy ).
- Add a 'Script Path' File/Link field to the entity, to control where a plugin script will be.
- Add a 'Ignore Projects' multi entity Project field to the entity, to control the list of projects where a plugin shouldn't be active.
- Edit your shotgunEventDaemon.conf file, and add the section :
 [pluginManager]
 sgEntity : CustomNonProjectEntity15 # the entity you enabled
 script_key = ??????? # The Shotgun script key to use by the pluginManager plugin
 script_name = ?????? # The Shotgun script name to use by the pluginManager plugin
- Copy this file in a place where your shotgunEventDaemon.py script can find it
"""

import logging
import os
import shotgun_api3 as sg
import re
import sys

def registerCallbacks(reg):
    """
    Register attribute and entity changes callbacks for plugins registered in Shotgun.
    Load plugins registered in Shotgun
    """

    reg.logger.debug('Loading pluginManager plugin.')

    # Retrieve config values
    my_name = reg.getName()
    cfg = reg.getConfig()
    if not cfg :
        raise ConfigError( "No config file found")
    reg.logger.debug( "Loading config for %s" % reg.getName() )
    settings = {}
    keys = [ 'sgEntity', 'script_key', 'script_name']
    for k in keys :
        settings[k] = cfg.get( my_name, k )
        reg.logger.debug( "Using %s %s" % ( k, settings[k] ) )
    # We will need access to the Engine from callbacks
    settings['engine'] = reg.getEngine()

    # Register all callbacks related to our custom entity

    # Attribute change callback
    eventFilter = { r'Shotgun_%s_Change' % settings['sgEntity'] : ['sg_status_list', 'sg_script_path', 'sg_ignore_projects' ] }
    reg.logger.debug("Registring %s", eventFilter )
    reg.registerCallback( settings['script_name'], settings['script_key'], changeEventCB, eventFilter, settings )

    # Entity change callbacks
    eventFilter = {
        r'Shotgun_%s_New' % settings['sgEntity'] : None,
        r'Shotgun_%s_Retirement' % settings['sgEntity'] : None,
        r'Shotgun_%s_Revival' % settings['sgEntity'] : None
        }
    reg.logger.debug("Registring %s", eventFilter )
    reg.registerCallback( settings['script_name'], settings['script_key'], entityEventCB, eventFilter, settings )

    # Get a list of all the existing plugins from Shotgun
    sgHandle = sg.Shotgun( reg.getEngine().config.getShotgunURL(), settings['script_name'], settings['script_key'] )
    plugins = sgHandle.find( settings['sgEntity'], [], ['sg_script_path', 'sg_status_list', 'sg_ignore_projects'] )
    reg.logger.debug( "Plugins : %s", plugins )
    for p in plugins :
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act'  and os.path.isfile( p['sg_script_path']['local_path'] ) :
            reg.logger.info( "Loading %s", p['sg_script_path']['name'] )
            pl = reg.getEngine().loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False )
            pl._pm_ignore_projects = p['sg_ignore_projects']

    #reg.logger.setLevel(logging.ERROR)

def changeEventCB(sg, logger, event, args):
    """
    A callback that treats plugins attributes changes.

    @param sg: Shotgun instance.
    @param logger: A preconfigured Python logging.Logger object
    @param event: A Shotgun event.
    @param args: The args passed in at the registerCallback call.
    """
    logger.debug("%s" % str(event))
    etype = event['event_type']
    attribute = event['attribute_name']
    entity = event['entity']
    if attribute == 'sg_status_list' :
        logger.info( "Status changed for %s", entity['name'] )
        # We need some details to know what to do
        p = sg.find_one( entity['type'], [[ 'id', 'is', entity['id']]], ['sg_script_path', 'sg_ignore_projects'] )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and os.path.isfile( p['sg_script_path']['local_path'] ) :
            if event['meta']['new_value'] == 'act' :
                logger.info('Loading %s', p['sg_script_path']['name'])
                pl = args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)
                pl._pm_ignore_projects = p['sg_ignore_projects']
            else : #Disable the plugin
                logger.info('Unloading %s', p['sg_script_path']['name'])
                args['engine'].unloadPlugin( p['sg_script_path']['local_path'])
    elif attribute == 'sg_script_path' : # Should unload and reload the plugin
        logger.info( "Script path changed for %s", entity['name'] )
        # We need some details to know what to do
        p = sg.find_one( entity['type'], [[ 'id', 'is', entity['id']]], ['sg_status_list', 'sg_script_path', 'sg_ignore_projects'] )
        old_val = event['meta']['old_value']
        # Unload the plugin if loaded
        if old_val : # Couldn't be loaded if empty or None
            file_path = old_val['file_path'] # This is not the full path, it is local to the storage
            # We need to rebuild the old path
            local_path = { 'darwin' : 'mac_path', 'win32' : 'windows_path', 'linux' : 'linux_path', 'linux2' : 'linux_path' }[ sys.platform]
            st = sg.find_one( 'LocalStorage', [[ 'id', 'is',  old_val['local_storage_id'] ]], [local_path ] )
            path = os.path.join( st[ local_path], file_path )
            logger.info('Unloading %s', os.path.basename( path ))
            args['engine'].unloadPlugin( path )
        # Reload the plugin if possible
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act' and os.path.isfile( p['sg_script_path']['local_path'] ) :
            logger.info('Loading %s', p['sg_script_path']['name'])
            pl = args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)
            pl._pm_ignore_projects = p['sg_ignore_projects']
    elif attribute == 'sg_ignore_projects' :
        logger.info( "'Ignore projects' changed for %s", entity['name'] )
        p = sg.find_one( entity['type'], [[ 'id', 'is', entity['id']]], ['sg_status_list', 'sg_script_path', 'sg_ignore_projects'] )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] :
            pl = args['engine'].getPlugin( p['sg_script_path']['local_path'] )
            if pl :
                pl._pm_ignore_projects = p['sg_ignore_projects']
         
def entityEventCB(sg, logger, event, args):
    """
    A callback that treat plugins entities changes

    @param sg: Shotgun instance.
    @param logger: A preconfigured Python logging.Logger object
    @param event: A Shotgun event.
    @param args: The args passed in at the registerCallback call.
    """
    logger.debug("%s" % str(event))
    etype = event['event_type']
    attribute = event['attribute_name']
    meta = event['meta']
    if re.search( 'Retirement$', etype ) : # Unload the plugin
        p = sg.find_one( meta['entity_type'], [[ 'id', 'is', meta['entity_id']]], ['sg_script_path'], retired_only=True )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] :
            logger.info('Unloading %s', p['sg_script_path']['name'])
            args['engine'].unloadPlugin( p['sg_script_path']['local_path'])
    elif re.search( 'Revival$', etype ) or re.search( 'New$', etype ): #Should reload the plugin
        p = sg.find_one( meta['entity_type'], [[ 'id', 'is', meta['entity_id']]], ['sg_script_path', 'sg_status_list', 'sg_ignore_projects'] )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act' and os.path.isfile( p['sg_script_path']['local_path'] ) :
            logger.info('Loading %s', p['sg_script_path']['name'])
            pl = args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)
            pl._pm_ignore_projects = p['sg_ignore_projects']


