import asyncio
import configparser
#import datetime
import isodate
import logging
import re

from apiclient.discovery import build

import yaboli
from yaboli.utils import *


class Video:
	DURATION_RE = r"P(\d+Y)?(\d+"
	def __init__(self, vid, title, duration, blocked):
		self.id = vid,
		self.title = title
		self.duration = isodate.parse_duration(duration)
		self.blocked = blocked

class YouTube:
	def __init__(self, api_key):
		self.service = build("youtube", "v3", developerKey=api_key)

	async def get_videos(self, vids):
		vids = ",".join(vids)
		query = self.service.videos().list(part="id,contentDetails,snippet", id=vids)
		details = await asyncify(query.execute)

		videos = {}
		for info in details["items"]:
			vid = info["id"]
			title = info["snippet"]["title"]
			duration = info["contentDetails"]["duration"]
			blocked = None

			video = Video(vid, title, duration, blocked)
			videos[vid] = video

		return videos

class Playlist:
	def __init__(self):
		self.waiting = []

		self.playing_task = None
		self.playing_video = None
		self.playing_until = None

	def add(self, video):
		position = len(self.waiting)
		self.waiting.append(video)
		return position

class ArgonDJBot(yaboli.Bot):
	SHORT_HELP = "Short help placeholder"
	LONG_HELP = "Long help placeholder"

	VIDEO_ID_RE = r"[a-zA-Z_-]{11}"
	# group 5: video id
	YOUTUBE_RE = r"((https?://)?(www\.)?(youtube\.com/(watch\?v=|embed/)|youtu\.be/))?(" + VIDEO_ID_RE + ")"
	YOUTUBE_RE_GROUP = 6

	def __init__(self, nick, room, api_key, cookiefile=None, password=None):
		super().__init__(nick, cookiefile=cookiefile)

		self.yt = YouTube(api_key)
		self.playlist = Playlist()

		#self.playing_task = None
		#self.playing_video = None
		#self.playing_until = None

		self.join_room(room, password=password)

	async def on_command_specific(self, room, message, command, nick, argstr):
		if similar(nick, room.session.nick) and not argstr:
			await self.botrulez_ping(room, message, command)
			await self.botrulez_help(room, message, command, text=self.LONG_HELP)
			await self.botrulez_uptime(room, message, command)
			await self.botrulez_kill(room, message, command)
			await self.botrulez_restart(room, message, command)

	async def on_command_general(self, room, message, command, argstr):
		if not argstr:
			await self.botrulez_ping(room, message, command)
			await self.botrulez_help(room, message, command, text=self.SHORT_HELP)

		await self.command_queue(room, message, command, argstr)

	@yaboli.command("queue", "q")
	async def command_queue(self, room, message, argstr):
		lines = []
		video_ids = []

		args = self.parse_args(argstr)
		if not args:
			await room.send("No videos specified", message.mid)
			return

		for arg in args:
			if arg == "-id": continue
			match = re.match(self.YOUTUBE_RE, arg)
			if match:
				video_ids.append(match.group(self.YOUTUBE_RE_GROUP))
			else:
				lines.append(f"Could not parse {arg!r}")

		videos = await self.yt.get_videos(video_ids)
		for vid in video_ids:
			video = videos.get(vid)
			if video:
				position = self.playlist.add(video)
				info = f"[{position:2}] {video.title!r} will be played in <beep>"
				lines.append(info)

		text = "\n".join(lines)
		await room.send(text, message.mid)

	@yaboli.command("list", "l")
	async def command_list(self, room, message, argstr):
		pass

def main(configfile):
	logging.basicConfig(level=logging.INFO)

	config = configparser.ConfigParser(allow_no_value=True)
	config.read(configfile)

	nick = config.get("general", "nick")
	cookiefile = config.get("general", "cookiefile", fallback=None)
	api_key = config.get("general", "apikey", fallback=None)
	room = config.get("general", "room")
	password = config.get("general", "password", fallback=None)

	bot = ArgonDJBot(nick, room, api_key, cookiefile=cookiefile, password=password)

	asyncio.get_event_loop().run_forever()

if __name__ == "__main__":
	main("argondjbot.conf")

