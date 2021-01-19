from davai_s_nami_bot.flow import Flow
from davai_s_nami_bot.tasks import get_edges

scheduler_flow = Flow(
    name="Test flow",
    edges=get_edges(),
)

scheduler_flow.run()
