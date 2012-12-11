"""
For detailed information please see

http://shotgunsoftware.github.com/shotgunEvents/api.html
"""
import logging
import os
import shotgun_api3 as sg
import re
import sys

def registerCallbacks(reg):
    """Register all necessary or appropriate callbacks for this plugin."""

    # Specify who should recieve email notifications when they are sent out.
    #
    #reg.setEmails('me@mydomain.com')

    # Use a preconfigured logging.Logger object to report info to log file or
    # email. By default error and critical messages will be reported via email
    # and logged to file, all other levels are logged to file.
    #
    #reg.logger.debug('Loading logArgs plugin.')

    # Register a callback to into the event processing system.
    #
    # Arguments:
    # - Shotgun script name
    # - Shotgun script key
    # - Callable
    # - Argument to pass through to the callable
    # - A filter to match events to so the callable is only invoked when
    #   appropriate
    #
    #eventFilter = {'Shotgun_Task_Change': ['sg_status_list']}
    eventFilter = None
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
    settings['engine'] = reg.getEngine()
    # Register all callbacks related to our custom entity
    # Attribute change callback
    eventFilter = { r'Shotgun_%s_Change' % settings['sgEntity'] : ['sg_status_list', 'sg_script_path' ] }
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
    plugins = sgHandle.find( settings['sgEntity'], [], ['sg_script_path', 'sg_status_list'] )
    reg.logger.debug( "Plugins : %s", plugins )
    for p in plugins :
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act'  and os.path.isfile( p['sg_script_path']['local_path'] ) :
            reg.logger.info( "Loading %s", p['sg_script_path']['name'] )
            reg.getEngine().loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False )

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
        p = sg.find_one( entity['type'], [[ 'id', 'is', entity['id']]], ['sg_script_path'] )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and os.path.isfile( p['sg_script_path']['local_path'] ) :
            if event['meta']['new_value'] == 'act' :
                logger.info('Loading %s', p['sg_script_path']['name'])
                args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)
            else : #Disable the plugin
                logger.info('Unloading %s', p['sg_script_path']['name'])
                args['engine'].unloadPlugin( p['sg_script_path']['local_path'])
    elif attribute == 'sg_script_path' : # Should unload and reload the plugin
        logger.info( "Script path changed for %s", entity['name'] )
        # We need some details to know what to do
        p = sg.find_one( entity['type'], [[ 'id', 'is', entity['id']]], ['sg_status_list', 'sg_script_path'] )
        old_val = event['meta']['old_value']
        file_path = old_val['file_path'] # This is not the full path, it is local to the storage
        # We need to rebuild the old path
        local_path = { 'darwin' : 'mac_path', 'win32' : 'windows_path', 'linux' : 'linux_path', 'linux2' : 'linux_path' }[ sys.platform]
        st = sg.find_one( 'LocalStorage', [[ 'id', 'is',  old_val['local_storage_id'] ]], [local_path ] )
        path = os.path.join( st[ local_path], file_path )
        logger.info('Unloading %s', os.path.basename( path ))
        args['engine'].unloadPlugin( path )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act' and os.path.isfile( p['sg_script_path']['local_path'] ) :
            logger.info('Loading %s', p['sg_script_path']['name'])
            args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)

         
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
        p = sg.find_one( meta['entity_type'], [[ 'id', 'is', meta['entity_id']]], ['sg_script_path', 'sg_status_list'] )
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act' and os.path.isfile( p['sg_script_path']['local_path'] ) :
            logger.info('Loading %s', p['sg_script_path']['name'])
            args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)


