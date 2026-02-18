#!/usr/bin/python
# -*- coding: utf-8 -*-
# -----------------------------------------
# Phantom sample App Connector python file
# -----------------------------------------

# Phantom App imports
import phantom.app as phantom
from phantom.action_result import ActionResult
from phantom.base_connector import BaseConnector

import json
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

# from polarityapp_consts import *


class RetVal(tuple):
    def __new__(cls, val1, val2=None):
        return tuple.__new__(RetVal, (val1, val2))


class PolarityappConnector(BaseConnector):
    def __init__(self):
        super(PolarityappConnector, self).__init__()
        self._state = None
        self._base_url = None

    def _process_empty_response(self, response, action_result):
        if response.status_code == 200:
            return RetVal(phantom.APP_SUCCESS, {})

        return RetVal(
            action_result.set_status(
                phantom.APP_ERROR, "Empty response and no information in the header"
            ),
            None,
        )

    def _process_html_response(self, response, action_result):
        status_code = response.status_code

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            error_text = soup.text
            split_lines = error_text.split("\n")
            split_lines = [x.strip() for x in split_lines if x.strip()]
            error_text = "\n".join(split_lines)
        except Exception:
            error_text = "Cannot parse error details"

        message = "Status Code: {0}. Data from server:\n{1}\n".format(
            status_code, error_text
        )

        message = message.replace("{", "{{").replace("}", "}}")
        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_json_response(self, r, action_result):
        try:
            resp_json = r.json()
        except Exception as e:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR,
                    "Unable to parse JSON response. Error: {0}".format(str(e)),
                ),
                None,
            )

        if 200 <= r.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, resp_json)

        message = "Error from server. Status Code: {0} Data from server: {1}".format(
            r.status_code, r.text.replace("{", "{{").replace("}", "}}")
        )

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_response(self, r, action_result):
        if hasattr(action_result, "add_debug_data"):
            action_result.add_debug_data({"r_status_code": r.status_code})
            action_result.add_debug_data({"r_text": r.text})
            action_result.add_debug_data({"r_headers": r.headers})

        if "json" in r.headers.get("Content-Type", ""):
            return self._process_json_response(r, action_result)

        if "html" in r.headers.get("Content-Type", ""):
            return self._process_html_response(r, action_result)

        if not r.text:
            return self._process_empty_response(r, action_result)

        message = "Can't process response from server. Status Code: {0} Data from server: {1}".format(
            r.status_code, r.text.replace("{", "{{").replace("}", "}}")
        )

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _make_rest_call(self, endpoint, action_result, method="get", **kwargs):
        config = self.get_config()

        resp_json = None

        try:
            request_func = getattr(requests, method)
        except AttributeError:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR, "Invalid method: {0}".format(method)
                ),
                resp_json,
            )

        url = self._base_url + endpoint

        try:
            r = request_func(
                url,
                verify=config.get("verify_server_cert", False),
                **kwargs,
            )
        except Exception as e:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR,
                    "Error Connecting to server. Details: {0}".format(str(e)),
                ),
                resp_json,
            )

        return self._process_response(r, action_result)

    def _clean_json_recursively(self, data):
        if isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                cleaned_v = self._clean_json_recursively(v)  # Use self.
                if cleaned_v not in (None, "", [], {}):
                    new_dict[k] = cleaned_v
            return new_dict

        elif isinstance(data, list):
            new_list = []
            for item in data:
                cleaned_item = self._clean_json_recursively(item)  # Use self.
                if cleaned_item not in (None, "", [], {}):
                    new_list.append(cleaned_item)
            return new_list

        else:
            return data

    def _handle_test_connectivity(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))

        self.save_progress("Connecting to endpoint")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        ret_val, response = self._make_rest_call(
            "/api/api-keys/me", action_result, params=None, headers=headers
        )

        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed.")
            return action_result.get_status()

        self.save_progress("Test Connectivity Passed")
        self.save_progress("\n+++++\n{0}".format(response))
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_search(self, param):
        self.save_progress(
            "In action handler for: {0}".format(self.get_action_identifier())
        )

        action_result = self.add_action_result(ActionResult(dict(param)))

        text = param["text"]

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        ret_val, response = self._make_rest_call(
            "/api/integrations", action_result, params=None, headers=headers
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()
            # pass

        ids = list(
            {
                opt.get("integration_id")
                for item in response.get("data", [])
                for opt in item.get("attributes", {}).get("options", [])
                if opt.get("integration_id")
            }
        )

        parse_payload = {
            "data": {"type": "parsed-entities", "attributes": {"text": text}}
        }
        ret_val, response = self._make_rest_call(
            "/api/parsed-entities",
            action_result,
            method="post",
            json=parse_payload,
            headers=headers,
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        etype = defaultdict(list)
        for e in (
            response.get("data", {}).get("attributes", {}).get("entities", []) or []
        ):
            t, v = e.get("type"), e.get("value")
            if t and v:
                etype[t].append(v)
        etype = dict(etype)

        entities = [
            {"value": v, "type": t, "channels": []}
            for t, vals in (etype or {}).items()
            for v in vals
        ]
        lookup_payload = {
            "data": {
                "type": "integration-lookups",
                "attributes": {"entities": entities},
            }
        }

        for iid in ids:
            path = f"/api/integrations/{iid}/lookup"
            ret_val, response = self._make_rest_call(
                path, action_result, method="post", json=lookup_payload, headers=headers
            )
            if phantom.is_fail(ret_val):
                self.save_progress(
                    f"[ERROR] Lookup for integration {iid} failed. Skipping."
                )
                continue
            bad_json = "errors" in response or not response.get("data", {}).get(
                "attributes", {}
            ).get("results")
            if not bad_json:
                good_json = self._clean_json_recursively(response)
                if good_json:
                    result_object = {"integration_id": iid, "result_data": good_json}
                    action_result.add_data(result_object)
                    self.save_progress("{0}".format(result_object))
        # action_result.add_data(polarityRes)

        summary = action_result.update_summary({})
        summary["IIDs"] = len(action_result.get_data())
        return action_result.set_status(phantom.APP_SUCCESS)

    def handle_action(self, param):
        ret_val = phantom.APP_SUCCESS
        action_id = self.get_action_identifier()

        self.debug_print("action_id", self.get_action_identifier())

        if action_id == "search":
            ret_val = self._handle_search(param)

        if action_id == "test_connectivity":
            ret_val = self._handle_test_connectivity(param)

        return ret_val

    def initialize(self):
        self._state = self.load_state()
        config = self.get_config()

        self._api_key = config.get("api_key")
        self._base_url = config.get("base_url")

        return phantom.APP_SUCCESS

    def finalize(self):
        self.save_state(self._state)
        return phantom.APP_SUCCESS


def main():
    import argparse

    argparser = argparse.ArgumentParser()

    argparser.add_argument("input_test_json", help="Input Test JSON file")
    argparser.add_argument("-u", "--username", help="username", required=False)
    argparser.add_argument("-p", "--password", help="password", required=False)

    args = argparser.parse_args()
    session_id = None

    username = args.username
    password = args.password

    if username is not None and password is None:
        import getpass

        password = getpass.getpass("Password: ")

    if username and password:
        try:
            login_url = PolarityappConnector._get_phantom_base_url() + "/login"

            print("Accessing the Login page")
            r = requests.get(login_url, verify=True)
            csrftoken = r.cookies["csrftoken"]

            data = dict()
            data["username"] = username
            data["password"] = password
            data["csrfmiddlewaretoken"] = csrftoken

            headers = dict()
            headers["Cookie"] = "csrftoken=" + csrftoken
            headers["Referer"] = login_url

            print("Logging into Platform to get the session id")
            r2 = requests.post(login_url, verify=True, data=data, headers=headers)
            session_id = r2.cookies["sessionid"]
        except Exception as e:
            print("Unable to get session id from the platform. Error: " + str(e))
            exit(1)

    with open(args.input_test_json) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print(json.dumps(in_json, indent=4))

        connector = PolarityappConnector()
        connector.print_progress_message = True

        if session_id is not None:
            in_json["user_session_token"] = session_id
            connector._set_csrf_info(csrftoken, headers["Referer"])

        ret_val = connector._handle_action(json.dumps(in_json))
        print(json.dumps(json.loads(ret_val), indent=4))

    exit(0)


if __name__ == "__main__":
    main()
