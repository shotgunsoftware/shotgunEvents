"""
Automatically calculate the Cut Duration on Shots when the Cut In or Cut Out value is changed.

Conversely, this example does not make any updates to Cut In or Cut Out values if the Cut Duration field 
is modified. You can modify that logic and/or the field names to match your specific workflow.
"""

def registerCallbacks(reg):
    matchEvents = {
        'Shotgun_Shot_Change': ['sg_cut_in','sg_cut_out'],
    }
    
    reg.registerCallback('$DEMO_SCRIPT_NAME$', '$DEMO_API_KEY$', calculateCutDuration, matchEvents, None)


def calculateCutDuration(sg, logger, event, args):
    """Calculate the Cut Duration as (Cut Out - Cut In) + 1 if all values are present"""

    if 'new_value' not in event['meta']:
        return
    
    # lookup the cut values for this Shot
    filters = [['id', 'is', event['entity']['id']]]
    fields = ['code','sg_cut_in','sg_cut_out','sg_cut_duration']
    shot = sg.find_one("Shot", filters, fields)
    if shot is None:
        return
    
    # calculate the new duration
    # if we don't have a value for both cut in and cut out, if there is an existing
    # value in the duration field, we unset the duration
    new_duration = None
    if shot['sg_cut_in'] is not None and shot['sg_cut_out'] is not None:
        new_duration = (shot['sg_cut_out'] - shot['sg_cut_in']) + 1
    elif not shot['sg_cut_duration']:
        return
    
    # update the Shot with the new duration
    sg.update("Shot", shot["id"], {'sg_cut_duration':new_duration})
    logger.info("%s: updated Cut Duration to %s" % (shot['code'], new_duration))

