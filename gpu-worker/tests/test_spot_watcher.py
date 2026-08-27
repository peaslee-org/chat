"""Unit tests for SpotWatcher — no EC2, AWS creds, or threads needed."""
from unittest.mock import MagicMock, patch


def make_watcher(queue_url="https://sqs.test/queue", receipt_handle="rh-123", region="us-east-1"):
    with patch("boto3.client") as mock_boto:
        mock_sqs = MagicMock()
        mock_boto.return_value = mock_sqs
        from gpu_worker.spot_watcher import SpotWatcher
        watcher = SpotWatcher(queue_url, receipt_handle, region)
        watcher._sqs = mock_sqs
        return watcher, mock_sqs


class TestSpotWatcher:

    def test_spot_interruption_releases_message(self):
        """A 200 response triggers change_message_visibility(VisibilityTimeout=0)."""
        watcher, mock_sqs = make_watcher()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            watcher._run()

        mock_sqs.change_message_visibility.assert_called_once_with(
            QueueUrl="https://sqs.test/queue",
            ReceiptHandle="rh-123",
            VisibilityTimeout=0,
        )

    def test_non_200_does_not_release_message(self):
        """A 404 response does not trigger SQS call."""
        watcher, mock_sqs = make_watcher()
        watcher._stop.set()  # stop immediately after first poll

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("requests.get", return_value=mock_response):
            watcher._run()

        mock_sqs.change_message_visibility.assert_not_called()

    def test_request_timeout_does_not_release_message(self):
        """A connection timeout (non-EC2 env) does not trigger SQS call."""
        import requests as req
        watcher, mock_sqs = make_watcher()
        watcher._stop.set()  # stop immediately after first poll

        with patch("requests.get", side_effect=req.exceptions.Timeout):
            watcher._run()

        mock_sqs.change_message_visibility.assert_not_called()

    def test_stop_event_exits_loop(self):
        """Setting stop event before poll interval causes _run to return without calling SQS."""
        watcher, mock_sqs = make_watcher()
        watcher._stop.set()  # already set — wait() returns True immediately

        with patch("requests.get") as mock_get:
            watcher._run()
            mock_get.assert_not_called()

        mock_sqs.change_message_visibility.assert_not_called()

    def test_spot_interruption_sets_process_flag(self):
        from gpu_worker.spot_watcher import SpotWatcher
        SpotWatcher.interrupted.clear()
        watcher, _ = make_watcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("requests.get", return_value=mock_response):
            watcher._run()
        assert SpotWatcher.interrupted.is_set()
        SpotWatcher.interrupted.clear()

    def test_idle_watcher_sets_flag_without_releasing_a_message(self):
        """The long-lived idle-mode watcher has no receipt handle — it must not touch SQS."""
        from gpu_worker.spot_watcher import SpotWatcher
        SpotWatcher.interrupted.clear()
        with patch("boto3.client") as mock_boto:
            watcher = SpotWatcher.idle_watcher("us-east-1")
        mock_boto.assert_not_called()

        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("requests.get", return_value=mock_response):
            watcher._run()

        assert SpotWatcher.interrupted.is_set()
        SpotWatcher.interrupted.clear()
