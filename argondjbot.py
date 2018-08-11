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

	def __init__(self, vid, title, duration, blocked, allowed):
		self.id = vid
		self.title = title
		self.raw_duration = isodate.parse_duration(duration)
		self.duration = self.raw_duration + datetime.timedelta(seconds=self.DELAY)
		self.blocked = list(sorted(blocked)) if blocked is not None else None
		self.allowed = list(sorted(allowed)) if allowed is not None else None

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
			blocked = info["contentDetails"].get("regionRestriction", {}).get("blocked", None)
			allowed = info["contentDetails"].get("regionRestriction", {}).get("allowed", None)

			video = Video(vid, title, duration, blocked, allowed)
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
		lines = [f"[{position:2}] {video.title!r} will be played in [{played_in}]"]

		if video.blocked is not None:
			lines.append(f"Blocked in {', '.join(video.blocked)}.")
		if video.allowed is not None:
			lines.append(f"Only viewable in {', '.join(video.allowed)}.")

		return lines

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
	COMMANDS = (
		"Simply playing videos:\n"
		"!queue, !q <urls or ids> - add videos to the queue\n"
		"!skip, !s - skip the currently playing video\n"
		"\n"
		"Advanced queue manipulation:\n"
		"!list, !l - display a list of currently queued videos\n"
		"NYI !delete, !del, !d <index> - deletes video at that index in the queue\n"
		"NYI !insert, !ins, !i <url or id> [before|after] <index> - insert a single video into the queue\n"
		"\n"
		"Fun stuff:\n"
		"!dramaticskip, !dskip, !ds - dramatic version of !skip\n"
		"!videoskip, !vskip, !vs - play a short video before the next queued video starts\n"
	)

	SHORT_HELP = "Short help placeholder"
	LONG_HELP = COMMANDS

	VIDEO_ID_RE = r"[a-zA-Z0-9_-]{11}"
	# group 5: video id
	YOUTUBE_RE = r"((https?://)?(www\.)?(youtube\.com/(watch\?v=|embed/)|youtu\.be/))?(" + VIDEO_ID_RE + ")"
	YOUTUBE_RE_GROUP = 6

	SKIP_VIDEOS = [
		"-6BlMb7IFFY", # Plop: Plunger to bald head
		"fClj2S6UzQA", # Ploop: Finger in metal cylinder
		"OfkViWKucCU", # Sold pupper dance
		"vGyHXW0lwZY", # Dog takes flight (maybe a bit loud?)
		"B6zk2Yd5ukc", # How to summon a cat on christmas
		"UJgwPRqVOoo", # Gecko party
		"7eysE77niUU", # I wanna be like you
		"ZH0lMFQifa4", # That's just neat
		"gdyp4Ez_T6I", # Wii soccer balls
		"CWGOt-Sic2s", # Running duck
		"6gxgfYKMUqE", # What happened
		"oa0arvrLZaM", # Dancing fish
		"Z7ioqD4ugh8", # parakeet
		"l1heD4T8Yco", # Dancing hamster
		"bLWGIYYEKfg", # urrg
		"4o5baMYWdtQ", # arf
		"y4aLXw7WwDM", # Muahahahaha
		"Ad9kJKCQ_kU", # Doggo's got talent
		"YxmdmJtUpjU", # Duck eating peas really fast
		"Ab_BdFr1BGg", # heard you were talkin shit (fat squirrel)
		"EixPRMs2jbY", # The microwave at work
		"9sxgbpTeiWQ", # Hedgehog
		"uqyHPs9D0z0", # Cat meaaaaaaaaaaaaaaaaaow
		"ua4nDQ-IGbY", # Cat vs. printing paper
		#"rMMOQOLze4Y", # Polite rally driver
		"UBftA7V4xak", # Dog dancing to "Shake that ass for me"
		"F-X4SLhorvw", # Look at all those
		"qcdkbcjTBoE", # Seal yells
		"-w-58hQ9dLk", # Jurassic park (melodica cover)
		"rYfkmDoOnmM", # Dog says mama
		"P1iqLU2KWJk", # Have you ever had a dream
		"bQtmm_lpUKI", # World's most pathetic elevator chime
		"lGVoZuMbTI4", # Xenostapler
		"2p1DIiv5GWs", # A drum beatin'
		"aHAgeOx1cBM", # Kill bill blow dryer
		"UkakfkiydPw", # Bem bebebem bebem bebem bem bem
		"t1r6BmNJX6Y", # Dog treat scream
		"sMKoNBRZM1M", # Super mario ping pong
		"DSi_FzQBNrU", # Markiplier do something spooky
		"KkDI4l2EldI", # SNAIL
		"NCu2saTv3QA", # Cat plays with foot
		"XOCuBpXi4zI", # Walking frog
		"Ul7IE3CTmSs", # annoyed news presenter
		"VV5JOQyUYNg", # Drum fill
		"PsLm6_qHeag", # Best dog in the world
		#"_7jvYfIDbyU", # Not a rapper, an adapter
		"Vh8l0x9uF-Y", # Man sneezes into trombone
		"rkZ9sSgGPrs", # Ghostly mouse howl
		"Fl2pSbNvp_Q", # One hell of a yawn
		"LlFmBB8wzg0", # It's soup
		"ne-gcy--MeY", # Crow on webcam
		"1s04tEDJVjY", # Smooth criminal cat
	]
	DRAMATICSKIP_VIDEOS = [
		"VHkP88fx164", # animated video
		"0pTOXwYtSVk", # longer video
		"eVLOVpwXYGY", # dramatic chipmunk remix
		"IqTerZkJaCU", # dramatic chipmunk vs shocked squirrel
		"G4BuQ_0oU0I", # 8-bit chipmunk
		"Wt0GiBkyCC0", # dramatic cat
	] + ["y8Kyi0WNg40"]*100 # original video

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
			await self.command_vskip(room, message, command)
			await self.command_dskip(room, message, command)

			await self.command_list(room, message, command)

		await self.command_queue(room, message, command, argstr)

	@yaboli.command("queue", "q")
	async def command_queue(self, room, message, argstr):
		video_ids = []
		lines_parse_error = []
		args = self.parse_args(argstr)
		for arg in args:
			if arg == "-id": continue
			match = re.match(self.YOUTUBE_RE, arg)
			if match:
				video_ids.append(match.group(self.YOUTUBE_RE_GROUP))
			else:
				lines_parse_error.append(f"Could not parse {arg!r}")

		lines = []
		lines_api_error = []
		videos = await self.yt.get_videos(video_ids)
		for vid in video_ids:
			video = videos.get(vid)
			if video:
				position = self.playlist.insert(video, message.sender.nick)
				until = self.playlist.playtime_until(position)

				info = Playlist.format_list_entry(video, position, until)
				lines.extend(info)
			else:
				lines_api_error.append(f"Video with id {vid} could not be accessed via the API")

		text = "\n".join(lines + lines_parse_error + lines_api_error)
		if not lines:
			await room.send("No valid videos specified\n" + text, message.mid)
			return

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

	@yaboli.command("videoskip", "vskip", "vs")
	async def command_vskip(self, room, message):
		vid = random.choice(self.SKIP_VIDEOS)
		videos = await self.yt.get_videos([vid])
		video = videos.get(vid)
		self.playlist.insert(video, room.session.nick, before=0)

		await room.send("Skipping to next video", message.mid)
		self.playlist.skip(room)

	@yaboli.command("dramaticskip", "dskip", "ds")
	async def command_dskip(self, room, message):
		vid = random.choice(self.DRAMATICSKIP_VIDEOS)
		videos = await self.yt.get_videos([vid])
		video = videos.get(vid)
		self.playlist.insert(video, room.session.nick, before=0)

		await room.send("Skipping to next video", message.mid)
		self.playlist.skip(room)

	@yaboli.command("list", "l")
	async def command_list(self, room, message):
		lines = []
		for position, (video, _) in self.playlist.items():
			until = self.playlist.playtime_until(position)
			info = Playlist.format_list_entry(video, position, until)
			lines.extend(info)

		if lines:
			text = "\n".join(lines)
		else:
			text = "Queue is empty"

		await room.send(text, message.mid)

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

