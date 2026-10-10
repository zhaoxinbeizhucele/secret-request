import json
import pytest
from secret_request.fields import validate_fields, validate_values, validate_agent

FIELDS = [{"id": "username", "label": "用户名", "type": "text"},
          {"id": "password", "label": "密码", "type": "password"},
          {"id": "key", "label": "私钥", "type": "textarea", "required": False}]


@pytest.mark.parametrize("fields", [[], FIELDS * 6, [FIELDS[0], FIELDS[0]],
    [{**FIELDS[0], "type": "file"}], [{**FIELDS[0], "id": "a.b"}],
    [{**FIELDS[0], "label": " "}], [{**FIELDS[0], "required": "false"}],
    [{**FIELDS[0], "value": "FAKE-DO-NOT-SEND"}], [{**FIELDS[0], "id": "constructor"}]])
def test_invalid_definitions(fields):
    with pytest.raises(ValueError): validate_fields(fields)


def test_values_preserve_whitespace_unicode_and_multiline():
    fields = validate_fields(FIELDS)
    value = json.dumps({"username": " 测试🔒 ", "password": "  fake  ", "key": "first\r\nsecond\n"}, ensure_ascii=False)
    assert validate_values(value, fields) == value
    assert validate_values("legacy raw", None) == "legacy raw"
    assert validate_values(json.dumps({"username": "user", "password": "fake", "key": ""}), fields)


@pytest.mark.parametrize("value", ['[]', '{}', '{"username": "one", "password": "x", "key": 1}',
    '{"username":"a", "username":"b", "password":"x", "key":""}',
    '{"username":"a", "password":"", "key":""}',
    '{"username":"a", "password":"x", "key":"", "extra":"fake"}',
    '{"username":"a\\nb", "password":"x", "key":""}',
    '{"username":"a", "password":"x\\u0000", "key":""}'])
def test_invalid_values(value):
    with pytest.raises(ValueError): validate_values(value, validate_fields(FIELDS))


@pytest.mark.parametrize("agent", ["", " ", "a\nb", "x" * 101, None])
def test_invalid_agent(agent):
    with pytest.raises(ValueError): validate_agent(agent)
