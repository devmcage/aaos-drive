import unittest

from . import bootstrap
from .fixtures import encoded
from custom_components.aaos_drive.api import DriveAuthError, DriveError, ReadOnlyDrive, folder_id
from custom_components.aaos_drive.model import InvalidExport


class Content:
    def __init__(self, data):
        self.data = data

    async def iter_chunked(self, _size):
        yield self.data


class Response:
    def __init__(self, payload, status=200, media=False):
        self.payload, self.status = payload, status
        self.content = Content(payload if media else encoded(payload))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.payload


class Session:
    """Intentionally implements GET only; any Drive write would fail the tests."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


async def token():
    return "synthetic-test-token"


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_pagination_and_shared_drive_parameters(self):
        session = Session(Response({"files": [{"id": "a", "name": "one"}], "nextPageToken": "second"}), Response({"files": [{"id": "b", "name": "two"}]}))
        drive = ReadOnlyDrive(session, token)
        self.assertEqual(len(await drive.children("car")), 2)
        self.assertEqual(session.calls[1][1]["params"]["pageToken"], "second")
        for url, options in session.calls:
            self.assertEqual(url, "https://www.googleapis.com/drive/v3/files")
            self.assertEqual(options["params"]["includeItemsFromAllDrives"], "true")
            self.assertFalse(options["allow_redirects"])
            self.assertEqual(options["headers"]["Authorization"], "Bearer synthetic-test-token")

    async def test_download_uses_media_get_only(self):
        session = Session(Response(b"zip-data", media=True))
        self.assertEqual(await ReadOnlyDrive(session, token).download("file"), b"zip-data")
        self.assertEqual(session.calls[0][1]["params"]["alt"], "media")

    async def test_response_limit_enforced(self):
        with self.assertRaises(InvalidExport):
            await ReadOnlyDrive(Session(Response(b"123456", media=True)), token).download("file", limit=5)

    async def test_401_requests_reauthorization(self):
        with self.assertRaises(DriveAuthError):
            await ReadOnlyDrive(Session(Response({}, status=401)), token).children("car")

    async def test_permission_403_requests_reauthorization(self):
        response = Response({"error": {"errors": [{"reason": "insufficientPermissions"}]}}, status=403)
        with self.assertRaises(DriveAuthError):
            await ReadOnlyDrive(Session(response), token).children("car")

    async def test_quota_403_is_retryable(self):
        response = Response({"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, status=403)
        with self.assertRaises(DriveError) as caught:
            await ReadOnlyDrive(Session(response), token).children("car")
        self.assertNotIsInstance(caught.exception, DriveAuthError)

    async def test_incomplete_listing_rejected(self):
        with self.assertRaises(DriveError):
            await ReadOnlyDrive(Session(Response({"files": [], "incompleteSearch": True})), token).children("car")

    async def test_duplicate_folder_names_rejected(self):
        folders = [{"id": "one", "name": "Sync", "mimeType": "application/vnd.google-apps.folder"}, {"id": "two", "name": "Sync", "mimeType": "application/vnd.google-apps.folder"}]
        with self.assertRaises(InvalidExport):
            await ReadOnlyDrive(Session(Response({"files": folders})), token).child_folder("car", "Sync")

    async def test_redirects_and_http_failures_not_followed(self):
        for status in (302, 404, 429, 500):
            with self.subTest(status=status), self.assertRaises(DriveError):
                await ReadOnlyDrive(Session(Response({}, status=status)), token).download("file")

    def test_folder_url_parsing_and_query_injection_rejection(self):
        self.assertEqual(folder_id("https://drive.google.com/drive/u/0/folders/car_123?usp=sharing"), "car_123")
        for value in ("car' or trashed=true", "https://evil.example/car", "../secrets"):
            with self.assertRaises(InvalidExport):
                folder_id(value)
