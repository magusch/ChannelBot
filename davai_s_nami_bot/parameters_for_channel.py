import json
from .dsn_site_session import parameter_for_dsn_channel

def get_approved_organization_ids():
    approved_organizations = json.loads(parameter_for_dsn_channel(
        {'site': 'timepad', 'name': 'approved_organization'}
    ).content)
    approved_ids = []
    for row in approved_organizations:
        approved_ids.append(row["value"])
    return approved_ids


def parameters_list_ids(site, param_name):
    approved_organizations = json.loads(parameter_for_dsn_channel(
        {'site': site, 'name': param_name}
    ).content)
    approved_ids = []
    for row in approved_organizations:
        approved_ids.append(row["value"])
    return approved_ids


def parameter_value(site, param_name):
    values = parameters_list_ids(site, param_name)
    if len(values)>0:
        values[0]
    else:
        None