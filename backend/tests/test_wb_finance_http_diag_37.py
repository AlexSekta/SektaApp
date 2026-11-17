from unittest.mock import patch, Mock
from backend.scripts.wb_finance_probe import post_finance


def test_http_diagnostic_report_id_is_attached(capsys):
    response = Mock(status_code=200)
    response.json.return_value = [{'rrdId': 3}]
    with patch('backend.scripts.wb_finance_probe.requests.post', return_value=response) as req:
        assert post_finance('private-token', '/api/finance/v1/sales-reports/detailed/511856341',
                            {'rrdId': 123, 'limit': 1000, 'fields': []}, diagnostic_report_id=511856341) == [{'rrdId':3}]
    logs = capsys.readouterr().out
    assert 'WB_FINANCE_HTTP_DIAG report=511856341 status=200' in logs
    assert 'private-token' not in logs
    assert req.call_args.kwargs['json']['rrdId'] == 123


def test_no_diagnostic_for_other_call(capsys):
    response = Mock(status_code=204)
    with patch('backend.scripts.wb_finance_probe.requests.post', return_value=response):
        assert post_finance('private-token', '/api/finance/v1/sales-reports/list', {}, diagnostic_report_id=None) == []
    assert 'WB_FINANCE_HTTP_DIAG' not in capsys.readouterr().out


def test_network_diagnostic(capsys):
    import requests
    with patch('backend.scripts.wb_finance_probe.requests.post', side_effect=requests.Timeout('sensitive')):
        assert post_finance('private-token', '/api/finance/v1/sales-reports/detailed/511856341', {}, diagnostic_report_id=511856341) is None
    logs = capsys.readouterr().out
    assert 'status=NETWORK_ERROR error=Timeout' in logs
    assert 'sensitive' not in logs
