"""
When a Task status is flipped to 'fin' (Final), lookup each downstream Task that is currently
'wtg' (Waiting To Start) and see if all upstream Tasks are now 'fin'. If so, flip the downstream Task
to 'rdy' (Ready To Start)

You can modify the status values in the logic to match your workflow.
"""

def registerCallbacks(reg):
    matchEvents = {
        'Shotgun_Task_Change': ['sg_status_list'],
    }
    
    reg.registerCallback('$DEMO_SCRIPT_NAME$', '$DEMO_API_KEY$', flipDownstreamTasks, matchEvents, None)


def flipDownstreamTasks(sg, logger, event, args):
    """Flip downstream Tasks to 'rdy' if all of their upstream Tasks are 'fin'"""
    
    # we only care about Tasks that have been finalled
    if 'new_value' not in event['meta'] or event['meta']['new_value'] != 'fin':
        return
    
    # downtream tasks that are currently wtg
    ds_filters = [
        ['upstream_tasks', 'is', event['entity']],
        ['sg_status_list', 'is', 'wtg'],
        ]
    fields = ['upstream_tasks']
    
    for ds_task in sg.find("Task", ds_filters, fields):
        change_status = True
        # don't change status unless *all* upstream tasks are fin
        if len(ds_task["upstream_tasks"]) > 1:
            logger.debug("Task #%d has multiple upstream Tasks", event['entity']['id'])
            us_filters = [
                ['downstream_tasks', 'is', ds_task],
                ['sg_status_list', 'is_not', 'fin'],
                ]
            if len(sg.find("Task", us_filters)) > 0:
                change_status = False
        
        if change_status:
            sg.update("Task",ds_task['id'], data={'sg_status_list' : 'rdy'})
            logger.info("Set Task #%s to 'rdy'", ds_task['id'])
