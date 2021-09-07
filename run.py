from davai_s_nami_bot.flow import Flow
from davai_s_nami_bot.tasks import get_edges, get_posting


scheduler_flow = Flow(edges=get_edges())
#scheduler_flow = Flow(edges=get_posting())

scheduler_flow.run()
