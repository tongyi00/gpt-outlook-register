import unittest
from unittest.mock import Mock

from auth_flow import AuthFlow
from config import Config


class AuthFlowAddPhoneTests(unittest.TestCase):
    def test_add_phone_send_normalizes_phone_and_adds_sms_channel(self):
        flow = AuthFlow(Config())
        flow._trace_http = Mock()

        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {"page": {"type": "phone_otp_verification"}}

        flow.session = Mock()
        flow.session.cookies.get.return_value = ""
        flow.session.post.return_value = response

        flow._add_phone_send("19027080724")

        sent_payload = flow.session.post.call_args.kwargs["json"]
        self.assertEqual(sent_payload, {
            "phone_number": "+19027080724",
            "channel": "sms",
        })

    def test_add_phone_send_error_includes_structured_diagnostics(self):
        flow = AuthFlow(Config())
        flow._trace_http = Mock()

        response = Mock()
        response.status_code = 400
        response.headers = {
            "x-request-id": "req-123",
            "cf-ray": "ray-456-SIN",
            "Content-Type": "application/json",
        }
        response.text = (
            '{"error":{"message":"Invalid phone number. Please try again.",'
            '"type":"invalid_request_error","param":"phone_number",'
            '"code":"invalid_phone_number"}}'
        )
        response.json.return_value = {
            "error": {
                "message": "Invalid phone number. Please try again.",
                "type": "invalid_request_error",
                "param": "phone_number",
                "code": "invalid_phone_number",
            }
        }

        flow.session = Mock()
        flow.session.cookies.get.return_value = ""
        flow.session.post.return_value = response

        with self.assertRaises(RuntimeError) as ctx:
            flow._add_phone_send("18253670199")

        message = str(ctx.exception)
        self.assertIn("add-phone/send failed", message)
        self.assertIn("http=400", message)
        self.assertIn("req_id=req-123", message)
        self.assertIn("cf_ray=ray-456-SIN", message)
        self.assertIn("phone=18253670199", message)
        self.assertIn("sent_phone=+18253670199", message)
        self.assertIn("has_plus=0", message)
        self.assertIn("digits_len=11", message)
        self.assertIn("error_code=invalid_phone_number", message)
        self.assertIn("error_param=phone_number", message)
        self.assertIn("error_type=invalid_request_error", message)
        self.assertIn("Invalid phone number. Please try again.", message)
        self.assertIn("payload={'phone_number': '+18253670199', 'channel': 'sms'}", message)


if __name__ == "__main__":
    unittest.main()
