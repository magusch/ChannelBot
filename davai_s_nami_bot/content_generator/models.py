from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint

# Use the same Base as the rest of the project's models to share the mapper registry
from ..database.models import Base, Events2Posts


class ContentGeneratorEventSelection(Base):
    __tablename__ = 'content_generator_eventselection'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False)
    generation_settings = Column(String, nullable=False, default='{}')  # Assuming JSONB is stored as String
    #created_by_id = Column(Integer, ForeignKey('auth_user.id', deferrable=True, initially='DEFERRED'), nullable=False)
    filter_set_id = Column(BigInteger, ForeignKey('content_generator_filterset.id', deferrable=True, initially='DEFERRED'), nullable=False)

    # Relationships can be defined here if needed
    filter = relationship("ContentGeneratorFilterSet", back_populates="event_selections")
    generated_posts = relationship("ContentGeneratorGeneratedPost", back_populates="event_selection")


class ContentGeneratorEventSelectionSelectedEvents(Base):
    __tablename__ = 'content_generator_eventselection_selected_events'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    eventselection_id = Column(BigInteger, ForeignKey('content_generator_eventselection.id', deferrable=True, initially='DEFERRED'), nullable=False)
    events2post_id = Column(BigInteger, ForeignKey('events_events2post.id', onupdate='CASCADE', ondelete='CASCADE', deferrable=True, initially='DEFERRED'), nullable=False)

    # Unique constraint to ensure no duplicate entries for the same selection and post
    __table_args__ = (
        UniqueConstraint('eventselection_id', 'events2post_id', name='content_generator_events_eventselection_id_events_e1d65ddd_uniq'),
    )

    # Add relationship to the actual event
    event = relationship("Events2Posts", foreign_keys=[events2post_id])


class ContentGeneratorFilterSet(Base):
    __tablename__ = 'content_generator_filterset'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(String, nullable=False)
    filter_type = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False)
    filter_params = Column(String, nullable=False)  # Assuming JSONB is stored as String

    # Add the missing relationship
    event_selections = relationship("ContentGeneratorEventSelection", back_populates="filter")


class ContentGeneratorGeneratedPost(Base):
    __tablename__ = 'content_generator_generatedpost'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    content = Column(String, nullable=False)
    status = Column(String(20), nullable=False)
    tags = Column(String, nullable=False)  # Assuming JSONB is stored as String
    media_files = Column(String, nullable=False)  # Assuming JSONB is stored as String
    event_selection_id = Column(BigInteger, ForeignKey('content_generator_eventselection.id', deferrable=True, initially='DEFERRED'), nullable=False)
    #generated_by_id = Column(Integer, ForeignKey('auth_user.id', deferrable=True, initially='DEFERRED'), nullable=False)
    post_template_id = Column(BigInteger, ForeignKey('content_generator_posttemplate.id', deferrable=True, initially='DEFERRED'), nullable=False)
    post_template = relationship("ContentGeneratorPostTemplate", back_populates="generated_posts")
    event_selection = relationship("ContentGeneratorEventSelection", back_populates="generated_posts")


class ContentGeneratorPostTemplate(Base):
    __tablename__ = 'content_generator_posttemplate'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    template_text = Column(String, nullable=False)
    variables = Column(String, nullable=False)  # Assuming JSONB is stored as String
    is_active = Column(Boolean, nullable=False)

    generated_posts = relationship("ContentGeneratorGeneratedPost", back_populates="post_template")


