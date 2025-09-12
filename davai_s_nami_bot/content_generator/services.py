from datetime import datetime, timedelta
import json

from typing import List, Dict, Any

from . import crud
from davai_s_nami_bot import crud as dsn_crud

from davai_s_nami_bot.pydantic_models import EventRequestParameters


class GeneratorPost:

    def __init__(self):
        pass

    # Make in model ContentGeneratorEventSelection new event selection by random filter set and also put events from Events2Posts to ContentGeneratorEventSelectionSelectedEvents
    def event_selection(self, filter_set_id: int = None) -> dict:
        filter_set = crud.get_filter(filter_set_id)
        if not filter_set:
            raise ValueError("Фильтр не найден")

        filtered_events = self.apply_filters(filter_set)
        if not filtered_events:
            return {}
        
        event_selection_dict = {
            'filter_set_id': filter_set['id'],
            'name':          filter_set['name'],
            'status':       'draft',
            'generation_settings': json.dumps(filter_set['filter_params']),
        }

        event_selection = crud.create_event_selection(event_selection_dict)

        crud.add_selected_events(event_selection, filtered_events)
        return event_selection

    def apply_filters(self, filter_set): # -> models.QuerySet:
        """Apply filter and return filtered events."""
        filter_params = filter_set['filter_params']

        today = datetime.today()
        week_ahead = today + timedelta(days=7)

        parameters = {
            'date_from': today, 'date_to': week_ahead, 'status': 'all'
        }

        if 'main_category' in filter_params:
            parameters['category'] = filter_params['main_category']
            if not isinstance(parameters['category'], list):
                parameters['category'] = [parameters['category']]

        if 'date_from' in filter_params:
            parameters['date_from'] = filter_params['date_from']

        if 'date_to' in filter_params:
            parameters['date_to'] = filter_params['date_to']

        if 'week_ahead' in filter_params:
            parameters['date_from'] = today
            parameters['date_to'] = week_ahead

        if 'this_week' in filter_params:
            start_week = today - timedelta(days=today.weekday())
            end_week = start_week + timedelta(days=7)

            parameters['date_from'] = start_week
            parameters['date_to'] = end_week

        if 'weekend' in filter_params:
            saturday = today + timedelta(5 - today.weekday())
            sunday = saturday + timedelta(days=1)

            parameters['date_from'] = saturday
            parameters['date_to'] = sunday

        if 'location' in filter_params:
            # Assuming 'location' is a string or a list of strings
            if isinstance(filter_params['location'], list):
                parameters['place'] = filter_params['location']
            else:
                parameters['place'] = [filter_params['location']]

        # if 'keywords' in params:
        #     q_objects = Q()
        #     for keyword in params['keywords']:
        #         q_objects |= Q(title__icontains=keyword) | Q(description__icontains=keyword)
        #     queryset = queryset.filter(q_objects)
        parameters['fields'] = ['id']
        params = EventRequestParameters(**parameters)
        answer = dsn_crud.get_events_by_date_and_category(params)
        return answer['events']

    def generate_post_by_template(self, event_selection_id: int = None, post_template_id: int = None, generated_by_id: int = None) -> Dict[str, Any]:
        # Fetch the post template
        post_template = crud.get_post_template(post_template_id)
        if not post_template:
            raise ValueError("Post template not found")

        event_selection = crud.get_event_selection(event_selection_id)
        selected_event_ids = crud.get_selected_events(event_selection['id'])
        if not selected_event_ids:
            raise ValueError("Selected Events not found for the event selection")
        
        parameters = {'ids': selected_event_ids, 'fields': post_template['variables']}
        params = EventRequestParameters(**parameters)
        selected_events = dsn_crud.get_approved_events(params)
        

        new_post = self.generate_post(post_template, selected_events)
        # Create a new generated post
        new_post = {
            'title': event_selection['name'],
            'content': new_post,
            'status': 'draft',  # Default status
            # 'tags': post_template.tags,
            # 'media_files': post_template.media_files,
            'event_selection_id': event_selection['id'],
            #'generated_by_id': generated_by_id or 1,
            'post_template_id': post_template['id'],
        }
        
        new_post = crud.create_generated_post(new_post)
       
        return {
            "id": new_post['id'],
            "title": new_post['title'],
            "content": new_post['content'],
            "status": new_post['status']
        }


    def generate_post(self, post_template: dict, selected_events: list[dict]) -> Dict[str, Any]:
        """Generates a post based on the selected events and the post template."""
        
        new_post = f"**{post_template['name']}**\n\n"
        for event in selected_events:
            # TODO: using vairables
            new_post += post_template['template_text'].format(
                title=event['title'],
                price=event['price'],
                prepared_text=event['prepared_text'],
                address=event['address']
            ) + "\n\n"
        # TODO: using AI make post
        return new_post