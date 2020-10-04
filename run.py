from davai_s_nami_bot.flow import Flow
from davai_s_nami_bot.tasks import get_edges
from davai_s_nami_bot.telegram import get_bot
from davai_s_nami_bot.logger import get_logger


log = get_logger()

scheduler_flow = Flow(
    name="Test flow",
    edges=get_edges(log=log),
    log=log,
    bot=get_bot(),
)

scheduler_flow.run()
