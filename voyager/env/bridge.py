import os
import os.path
import time
import warnings
from typing import SupportsFloat, Any, Tuple, Dict

import requests
import json

import gymnasium as gym
from gymnasium.core import ObsType

import voyager.utils as U

from .minecraft_launcher import MinecraftInstance
from .process_monitor import SubprocessMonitor


class VoyagerEnv(gym.Env):
    def __init__(
        self,
        mc_port=None,
        azure_login=None,
        server_host="http://127.0.0.1",
        server_port=3000,
        request_timeout=600,
        log_path="./logs",
    ):
        if not mc_port and not azure_login:
            raise ValueError("Either mc_port or azure_login must be specified")
        if mc_port and azure_login:
            warnings.warn(
                "Both mc_port and mc_login are specified, mc_port will be ignored"
            )
        self.mc_port = mc_port
        self.azure_login = azure_login
        self.server = f"{server_host}:{server_port}"
        self.server_port = server_port
        self.request_timeout = request_timeout
        self.log_path = log_path
        self.session = requests.Session()
        self.session.trust_env = False
        self.mineflayer = self.get_mineflayer_process(server_port)
        if azure_login:
            self.mc_instance = self.get_mc_instance()
        else:
            self.mc_instance = None
        self.has_reset = False
        self.reset_options = None
        self.connected = False
        self.server_paused = False
        self.pause_enabled = os.environ.get("VOYAGER_ENABLE_PAUSE") == "1"
        viewer_port = os.environ.get("VOYAGER_VIEWER_PORT")
        self.viewer_port = int(viewer_port) if viewer_port else None
        self.viewer_first_person = os.environ.get("VOYAGER_VIEWER_FIRST_PERSON") == "1"
        self.viewer_draw_path = os.environ.get("VOYAGER_VIEWER_DRAW_PATH", "1") != "0"

    def _post(self, path, payload=None, timeout=None):
        return self.session.post(
            f"{self.server}{path}",
            json=payload,
            timeout=self.request_timeout if timeout is None else timeout,
        )

    def get_mineflayer_process(self, server_port):
        U.f_mkdir(self.log_path, "mineflayer")
        file_path = os.path.abspath(os.path.dirname(__file__))
        return SubprocessMonitor(
            commands=[
                "node",
                U.f_join(file_path, "mineflayer/index.js"),
                str(server_port),
            ],
            name="mineflayer",
            ready_match=r"Server started on port (\d+)",
            log_path=U.f_join(self.log_path, "mineflayer"),
        )

    def get_mc_instance(self):
        print("Creating Minecraft server")
        U.f_mkdir(self.log_path, "minecraft")
        return MinecraftInstance(
            **self.azure_login,
            mineflayer=self.mineflayer,
            log_path=U.f_join(self.log_path, "minecraft"),
        )

    def check_process(self):
        if self.mc_instance and not self.mc_instance.is_running:
            # if self.mc_instance:
            #     self.mc_instance.check_process()
            #     if not self.mc_instance.is_running:
            print("Starting Minecraft server")
            self.mc_instance.run()
            self.mc_port = self.mc_instance.port
            self.reset_options["port"] = self.mc_instance.port
            print(f"Server started on port {self.reset_options['port']}")
        retry = 0
        while not self.mineflayer.is_running:
            print("Mineflayer process has exited, restarting")
            self.mineflayer.run()
            if not self.mineflayer.is_running:
                if retry > 3:
                    raise RuntimeError("Mineflayer process failed to start")
                else:
                    continue
            print(self.mineflayer.ready_line)
            self.server_paused = False
            start_error = None
            for start_attempt in range(3):
                try:
                    res = self._post("/start", self.reset_options)
                except requests.RequestException as err:
                    start_error = err
                else:
                    if res.status_code == 200:
                        return res.json()
                    start_error = RuntimeError(
                        f"Minecraft server reply with code {res.status_code}: {res.text}"
                    )

                if start_attempt < 2:
                    print(
                        f"Start request failed ({start_error}); retrying mineflayer start."
                    )
                    self.mineflayer.stop()
                    time.sleep(1)
                    self.mineflayer.run()
                    if not self.mineflayer.is_running:
                        break
                    print(self.mineflayer.ready_line)
                    self.server_paused = False

            self.mineflayer.stop()
            raise RuntimeError("Failed to start mineflayer bot") from start_error

    def step(
        self,
        code: str,
        programs: str = "",
    ) -> Tuple[ObsType, SupportsFloat, bool, bool, Dict[str, Any]]:
        if not self.has_reset:
            raise RuntimeError("Environment has not been reset yet")
        data = {
            "code": code,
            "programs": programs,
        }
        last_error = None
        for attempt in range(2):
            self.check_process()
            self.unpause()
            try:
                # Step handlers can spend almost the full action timeout inside
                # mineflayer before emitting a final observation or error.
                res = self._post("/step", data, timeout=self.request_timeout + 30)
                if res.status_code == 200:
                    returned_data = res.json()
                    self.pause()
                    return json.loads(returned_data)
                last_error = RuntimeError(
                    f"Failed to step Minecraft server ({res.status_code}): {res.text}"
                )
            except requests.RequestException as e:
                last_error = e

            if attempt == 0:
                print(f"Step request failed ({last_error}); restarting mineflayer.")
                self.server_paused = False
                self.mineflayer.stop()
                time.sleep(1)
                continue

            raise RuntimeError("Failed to step Minecraft server") from last_error

    def render(self):
        raise NotImplementedError("render is not implemented")

    def reset(
        self,
        *,
        seed=None,
        options=None,
    ) -> Tuple[ObsType, Dict[str, Any]]:
        if options is None:
            options = {}

        if options.get("inventory", {}) and options.get("mode", "hard") != "hard":
            raise RuntimeError("inventory can only be set when options is hard")

        self.reset_options = {
            "port": self.mc_port,
            "reset": options.get("mode", "hard"),
            "inventory": options.get("inventory", {}),
            "equipment": options.get("equipment", []),
            "spread": options.get("spread", False),
            "waitTicks": options.get("wait_ticks", 5),
            "position": options.get("position", None),
            "viewerPort": self.viewer_port,
            "viewerFirstPerson": self.viewer_first_person,
            "viewerDrawPath": self.viewer_draw_path,
        }

        self.unpause()
        self.mineflayer.stop()
        time.sleep(1)  # wait for mineflayer to exit

        returned_data = self.check_process()
        self.has_reset = True
        self.connected = True
        # All the reset in step will be soft
        self.reset_options["reset"] = "soft"
        self.pause()
        return json.loads(returned_data)

    def close(self):
        self.unpause()
        if self.connected:
            try:
                res = self._post("/stop")
                if res.status_code == 200:
                    self.connected = False
            except requests.RequestException:
                self.connected = False
        if self.mc_instance:
            self.mc_instance.stop()
        self.mineflayer.stop()
        return not self.connected

    def pause(self):
        if not self.pause_enabled:
            self.server_paused = False
            return False
        if self.mineflayer.is_running and not self.server_paused:
            try:
                res = self._post("/pause")
                if res.status_code == 200:
                    self.server_paused = True
            except requests.RequestException as e:
                print(f"Pause request failed: {e}")
                self.server_paused = False
        return self.server_paused

    def unpause(self):
        if not self.pause_enabled:
            self.server_paused = False
            return False
        if self.mineflayer.is_running and self.server_paused:
            try:
                res = self._post("/pause")
                if res.status_code == 200:
                    self.server_paused = False
                else:
                    print(res.json())
            except requests.RequestException as e:
                print(f"Unpause request failed: {e}")
                self.server_paused = False
        return self.server_paused
