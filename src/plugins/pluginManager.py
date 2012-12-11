"""
For detailed information please see

http://shotgunsoftware.github.com/shotgunEvents/api.html
"""
import logging
import os
import shotgun_api3 as sg
import re
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
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act' :
            reg.logger.info( "Loading %s", p['sg_script_path']['name'] )
            reg.getEngine().loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False )
    # Set the logging level for this particular plugin. Let error and above
    # messages through but block info and lower. This is particularly usefull
    # for enabling and disabling debugging on a per plugin basis.
    #reg.logger.setLevel(logging.ERROR)

def changeEventCB(sg, logger, event, args):
    """
    A callback that logs its arguments.

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
        if p['sg_script_path'] and p['sg_script_path']['local_path'] :
            if event['meta']['new_value'] == 'act' :
                logger.info('Loading %s', p['sg_script_path']['name'])
                args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)
            else : #Disable the plugin
                logger.info('Unloading %s', p['sg_script_path']['name'])
                args['engine'].unloadPlugin( p['sg_script_path']['local_path'])
    elif attribute == 'sg_script_path' : # Should unload and reload the plugin
        logger.info( "Script path changed for %s", entity['name'] )
        # We need some details to know what to do
        p = sg.find_one( entity['type'], [[ 'id', 'is', entity['id']]], ['sg_status_list'] )
        spath = event['meta']['new_value']
        if p['sg_script_path'] and p['sg_script_path']['local_path'] :
            if event['meta']['new_value'] == 'act' :
                logger.info('Loading %s', p['sg_script_path']['name'])
                args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)
            else : #Disable the plugin
                logger.info('Unloading %s', p['sg_script_path']['name'])
                args['engine'].unloadPlugin( p['sg_script_path']['local_path'])

         
def entityEventCB(sg, logger, event, args):
    """
    A callback that logs its arguments.

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
        if p['sg_script_path'] and p['sg_script_path']['local_path'] and p['sg_status_list'] == 'act' :
            logger.info('Loading %s', p['sg_script_path']['name'])
            args['engine'].loadPlugin( p['sg_script_path']['local_path'], autoDiscover=False)


