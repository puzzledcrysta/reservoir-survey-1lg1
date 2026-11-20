from decimal import Decimal
import pytest
from app.errors import DataError
from app.modules.domain.rule import evaluate


def test_crossing(cases):
    actual, evidence = evaluate(cases['crossing'])
    assert actual == Decimal('10.000')
    assert evidence and all(len(row)==3 for row in evidence)


def test_trapezoid(cases):
    actual, evidence = evaluate(cases['trapezoid'])
    assert actual == Decimal('120.000')


def test_fill_only(cases):
    actual, evidence = evaluate(cases['fill_only'])
    assert actual == Decimal('0.000')


def test_fraction(cases):
    # TRAP-10
    actual, evidence = evaluate(cases['fraction'])
    assert actual == Decimal('0.333')


def test_same_chain(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['same_chain'])
    assert error.value.code in {'BUSINESS','NUMBER','RANGE','TIMESTAMP'}


def test_single(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['single'])
    assert error.value.code in {'BUSINESS','NUMBER','RANGE','TIMESTAMP'}


def test_bad_baseline(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['bad_baseline'])
    assert error.value.code in {'BUSINESS','NUMBER','RANGE','TIMESTAMP'}

