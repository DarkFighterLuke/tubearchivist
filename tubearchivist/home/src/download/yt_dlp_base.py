"""
functionality:
- base class to make all calls to yt-dlp
- handle yt-dlp errors
"""

import os
from datetime import datetime
from http import cookiejar
from io import StringIO

import yt_dlp
from home.src.ta.ta_redis import RedisArchivist


class YtWrap:
    """wrap calls to yt"""

    OBS_BASE = {
        "default_search": "ytsearch",
        "quiet": True,
        "check_formats": "selected",
        "socket_timeout": 2,
    }

    def __init__(self, obs_request, config=False):
        self.obs_request = obs_request
        self.config = config
        self.build_obs()

    def build_obs(self):
        """build yt-dlp obs"""
        self.obs = self.OBS_BASE.copy()
        self.obs.update(self.obs_request)
        if self.config:
            self.add_cookie()

    def add_cookie(self):
        """add cookie if enabled"""
        if self.config["downloads"]["cookie_import"]:
            cookie_io = CookieHandler(self.config).get()
            self.obs["cookiefile"] = cookie_io

    def download(self, url):
        """make download request"""
        with yt_dlp.YoutubeDL(self.obs) as ydl:
            try:
                ydl.download([url])
            except yt_dlp.utils.DownloadError:
                print(f"{url}: failed to download.")
                return False

        return True

    def extract(self, url):
        """make extract request"""
        try:
            response = yt_dlp.YoutubeDL(self.obs).extract_info(url)
        except cookiejar.LoadError:
            print("cookie file is invalid")
            return False
        except (yt_dlp.utils.ExtractorError, yt_dlp.utils.DownloadError):
            print(f"{url}: failed to get info from youtube")
            return False

        return response


class CookieHandler:
    """handle youtube cookie for yt-dlp"""

    def __init__(self, config):
        self.cookie_io = False
        self.config = config

    def get(self):
        """get cookie io stream"""
        cookie = RedisArchivist().get_message("cookie")
        self.cookie_io = StringIO(cookie)
        return self.cookie_io

    def import_cookie(self):
        """import cookie from file"""
        cache_path = self.config["application"]["cache_dir"]
        import_path = os.path.join(cache_path, "import", "cookies.google.txt")
        with open(import_path, encoding="utf-8") as cookie_file:
            cookie = cookie_file.read()

        self.set_cookie(cookie)

        os.remove(import_path)
        print("cookie: import successful")

    def set_cookie(self, cookie):
        """set cookie str and activate in cofig"""
        RedisArchivist().set_message("cookie", cookie)
        path = ".downloads.cookie_import"
        RedisArchivist().set_message("config", True, path=path)
        self.config["downloads"]["cookie_import"] = True
        print("cookie: activated and stored in Redis")

    @staticmethod
    def revoke():
        """revoke cookie"""
        RedisArchivist().del_message("cookie")
        RedisArchivist().set_message(
            "config", False, path=".downloads.cookie_import"
        )
        print("cookie: revoked")

    def validate(self):
        """validate cookie using the liked videos playlist"""
        print("validating cookie")
        obs_request = {
            "skip_download": True,
            "extract_flat": True,
        }
        validator = YtWrap(obs_request, self.config)
        response = bool(validator.extract("LL"))
        self.store_validation(response)

        # update in redis to avoid expiring
        modified = validator.obs["cookiefile"].getvalue()
        if modified:
            RedisArchivist().set_message("cookie", modified)

        if not response:
            mess_dict = {
                "status": "message:download",
                "level": "error",
                "title": "Cookie validation failed, exiting...",
                "message": "",
            }
            RedisArchivist().set_message(
                "message:download", mess_dict, expire=4
            )
            print("cookie validation failed, exiting...")

        return response

    @staticmethod
    def store_validation(response):
        """remember last validation"""
        now = datetime.now()
        message = {
            "status": response,
            "validated": int(now.strftime("%s")),
            "validated_str": now.strftime("%Y-%m-%d %H:%M"),
        }
        RedisArchivist().set_message("cookie:valid", message)
