from davai_s_nami_bot.crud import (
    resolve_main_category_id,
    OTHER_CATEGORY_NAME,
    UNCATEGORIZED_CATEGORY_ID,
)
from davai_s_nami_bot.database.models import Category, SubCategory


def test_existing_subcategory_returns_its_category_id(db_session_fixture):
    db = db_session_fixture
    cat = Category(name="Концерты")
    db.add(cat)
    db.flush()
    db.add(SubCategory(name="Рок-концерты", category_id=cat.id))
    db.commit()

    result = resolve_main_category_id(db, category_str="Рок-концерты")
    assert result == cat.id


def test_new_subcategory_created_and_linked_to_other(db_session_fixture):
    db = db_session_fixture

    result = resolve_main_category_id(db, category_str="Караоке-баттл")

    other = db.query(Category).filter(Category.name == OTHER_CATEGORY_NAME).one()
    sub = db.query(SubCategory).filter(SubCategory.name == "Караоке-баттл").one()
    assert result == other.id
    assert sub.category_id == other.id


def test_existing_subcategory_without_category_backfills_to_other(db_session_fixture):
    db = db_session_fixture
    db.add(SubCategory(name="Сиротская", category_id=None))
    db.commit()

    result = resolve_main_category_id(db, category_str="Сиротская")

    other = db.query(Category).filter(Category.name == OTHER_CATEGORY_NAME).one()
    sub = db.query(SubCategory).filter(SubCategory.name == "Сиротская").one()
    assert result == other.id
    assert sub.category_id == other.id


def test_existing_main_category_id_is_kept(db_session_fixture):
    db = db_session_fixture
    cat = Category(name="Кино")
    db.add(cat)
    db.flush()

    result = resolve_main_category_id(
        db,
        category_str="Что угодно",
        current_main_category_id=cat.id,
    )
    assert result == cat.id
    assert db.query(SubCategory).filter(SubCategory.name == "Что угодно").first() is None


def test_uncategorized_id_treated_as_null_and_re_resolved(db_session_fixture):
    db = db_session_fixture
    target = Category(name="Театр")
    db.add(target)
    db.flush()
    db.add(SubCategory(name="Спектакль", category_id=target.id))
    db.commit()

    result = resolve_main_category_id(
        db,
        category_str="Спектакль",
        current_main_category_id=UNCATEGORIZED_CATEGORY_ID,
    )
    assert result == target.id


def test_empty_category_falls_back_to_keyword_inference(db_session_fixture):
    db = db_session_fixture

    result = resolve_main_category_id(
        db,
        category_str=None,
        title="Открытый кинопоказ в парке",
        full_text="приходите смотреть фильм",
    )
    # Keyword 'кинопоказ' → category_id 3 (Кино) per scoring._CATEGORY_KEYWORDS
    assert result == 3
    # Should not have written anything
    assert db.query(SubCategory).count() == 0
    assert db.query(Category).count() == 0


def test_unknown_category_with_no_keywords_returns_none(db_session_fixture):
    db = db_session_fixture

    result = resolve_main_category_id(
        db,
        category_str=None,
        title="abc",
        full_text="def",
    )
    assert result is None


def test_write_false_does_not_create_subcategory(db_session_fixture):
    db = db_session_fixture

    result = resolve_main_category_id(
        db,
        category_str="Неизвестная категория",
        title="Открытый кинопоказ в парке",
        full_text="",
        write=False,
    )
    # Falls back to keyword guess (кинопоказ → 3) instead of writing
    assert result == 3
    assert db.query(SubCategory).count() == 0
    assert db.query(Category).count() == 0
