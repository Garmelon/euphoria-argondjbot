import asyncio
import configparser
import datetime
import isodate
import logging
import random
import re
import time

from apiclient.discovery import build

import yaboli
from yaboli.utils import *


class Video:
	DURATION_RE = r"P(\d+Y)?(\d+"
	DELAY = 2

	def __init__(self, vid, title, duration, blocked):
		self.id = vid
		self.title = title
		self.raw_duration = isodate.parse_duration(duration)
		self.duration = self.raw_duration + datetime.timedelta(seconds=self.DELAY)
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

	# formatting functions

	@staticmethod
	def format_duration(dt):
		seconds = int(dt.total_seconds())

		hours = seconds // (60*60)
		seconds -= hours * (60*60)

		minutes = seconds // 60
		seconds -= minutes * 60

		return f"{hours:02}:{minutes:02}:{seconds:02}"

	@staticmethod
	def format_list_entry(video, position, played_in):
		played_in = Playlist.format_duration(played_in)
		return f"[{position:2}] {video.title!r} will be played in [{played_in}]"

	@staticmethod
	def format_play(video, player):
		raw_duration = Playlist.format_duration(video.raw_duration)
		player = mention(player, ping=False)
		lines = [
			f"[{raw_duration}] {video.title!r} from {player}",
			f"!play youtube.com/watch?v={video.id}",
		]
		return "\n".join(lines)

	# commands regarding currently playing video

	def play(self, room):
		if self.playing_task is None or self.playing_task.done():
			self.playing_task = asyncio.ensure_future(self._play(room))
			#asyncio.ensure_future(self._play(room))

	def skip(self, room):
		if self.playing_task and not self.playing_task.done():
			self.playing_task.cancel()
			self.playing_task = None
		self.play(room)

	async def _play(self, room):
		while self.waiting:
			video, player = self.waiting.pop(0)
			duration = video.duration.total_seconds()

			self.playing_video = video
			self.playing_until = time.time() + duration

			message = self.format_play(video, player)
			await room.send(message)

			await asyncio.sleep(duration)

		self.playing_task = None
		self.playing_video = None
		self.playing_until = None

	# commands modifying the playlist

	def insert(self, video, player, before=None):
		element = (video, player)
		if before is None:
			position = len(self.waiting)
			self.waiting.append(element)
		else:
			self.waiting.insert(before, element)
			position = before
		return position

	# playlist info

	def empty(self):
		return not bool(self.waiting)

	def items(self):
		return enumerate(self.waiting)

	def playtime_left(self):
		if self.playing_until:
			seconds = self.playing_until - time.time()
			return datetime.timedelta(seconds=seconds)
		else:
			return datetime.timedelta()

	def playtime_until(self, position=None):
		if position is None:
			videos = self.waiting
		else:
			videos = self.waiting[:position]

		video_sum = sum((video.duration for video, _ in videos), datetime.timedelta())
		return self.playtime_left() + video_sum

class ArgonDJBot(yaboli.Bot):
	SHORT_HELP = "Short help placeholder"
	LONG_HELP = "Long help placeholder"

	VIDEO_ID_RE = r"[a-zA-Z0-9_-]{11}"
	# group 5: video id
	YOUTUBE_RE = r"((https?://)?(www\.)?(youtube\.com/(watch\?v=|embed/)|youtu\.be/))?(" + VIDEO_ID_RE + ")"
	YOUTUBE_RE_GROUP = 6

	SKIP_VIDEOS = [
		"-6BlMb7IFFY", # Plop: Plunger to bald head
		"fClj2S6UzQA", # Ploop: Finger in metal cylinder
	]

	def __init__(self, nick, room, api_key, cookiefile=None, password=None):
		super().__init__(nick, cookiefile=cookiefile)

		self.yt = YouTube(api_key)
		self.playlist = Playlist()

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

			await self.command_skip(room, message, command)

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
				position = self.playlist.insert(video, message.sender.nick)
				until = self.playlist.playtime_until(position)

				info = Playlist.format_list_entry(video, position, until)
				lines.append(info)

		text = "\n".join(lines)
		await room.send(text, message.mid)

		self.playlist.play(room)

	@yaboli.command("skip", "s")
	async def command_skip(self, room, message):
		if self.playlist.empty():
			vid = random.choice(self.SKIP_VIDEOS)
			videos = await self.yt.get_videos([vid])
			video = videos.get(vid)
			self.playlist.insert(video, room.session.nick, before=0)

		await room.send("Skipping to next video", message.mid)
		self.playlist.skip(room)

	@yaboli.command("list", "l")
	async def command_list(self, room, message, argstr):
		pass

def main(configfile):
	#asyncio.get_event_loop().set_debug(True)
	#logging.basicConfig(level=logging.DEBUG)
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

