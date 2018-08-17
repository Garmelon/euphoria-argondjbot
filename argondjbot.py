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
	DELAY = 4

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
	COUNTRIES = { # according to en.wikipedia.org/wiki/ISO_3166-1_alpha-2, 2018-08-17 18:12:15 UTC
		"AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU",
		"AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL",
		"BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY", "BZ", "CA", "CC",
		"CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN", "CO", "CR", "CU", "CV",
		"CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM", "DO", "DZ", "EC", "EE", "EG",
		"EH", "ER", "ES", "ET", "FI", "FJ", "FK", "FM", "FO", "FR", "GA", "GB", "GD",
		"GE", "GF", "GG", "GH", "GI", "GL", "GM", "GN", "GP", "GQ", "GR", "GS", "GT",
		"GU", "GW", "GY", "HK", "HM", "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM",
		"IN", "IO", "IQ", "IR", "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH",
		"KI", "KM", "KN", "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK",
		"LR", "LS", "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH",
		"MK", "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
		"MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP", "NR",
		"NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM", "PN", "PR",
		"PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW", "SA", "SB", "SC",
		"SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS",
		"ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL",
		"TM", "TN", "TO", "TR", "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY",
		"UZ", "VA", "VC", "VE", "VG", "VI", "VN", "VU", "WF", "WS", "YE", "YT", "ZA",
		"ZM", "ZW"
	}
	COMMON_COUNTRIES = {"DE", "FI", "FR", "GB", "IT", "JP", "NL", "PT", "US"}

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

		blocked = None
		if video.blocked is not None:
			blocked = set(video.blocked)
			#lines.append(f"Blocked in {', '.join(video.blocked)}.")
		if video.allowed is not None:
			blocked = Playlist.COUNTRIES - set(video.allowed)
			#lines.append(f"Only viewable in {', '.join(video.allowed)}.")
		if blocked is not None:
			common = sorted(blocked & Playlist.COMMON_COUNTRIES)
			uncommon = sorted(blocked - Playlist.COMMON_COUNTRIES)

			if common:
				if uncommon:
					text = f"Blocked in {', '.join(common)} and {len(uncommon)} other "
					text += "country." if len(uncommon) == 1 else "countries."
				else:
					text = f"Blocked in {', '.join(common)}."
				lines.append(text)
			elif uncommon:
				if len(uncommon) <= 10:
					text = f"Blocked in {', '.join(uncommon)}."
				else:
					text = f"Blocked in {len(uncommon)} "
					text += "country." if len(uncommon) == 1 else "countries."
				lines.append(text)

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

	@staticmethod
	def format_next(video, player):
		if video and player:
			player = mention(player, ping=False)
			return f"Next: {video.title!r} from {player}"
		else:
			return "Next: Nothing"

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

			text = self.format_play(video, player)
			msg = await room.send(text)

			next_video = self.next()
			video, player = next_video if next_video else (None, None)
			text = self.format_next(video, player)
			await room.send(text, msg.mid)

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
			return position
		elif before >= 0:
			self.waiting.insert(before, element)
			return min(before, len(self.waiting) - 1)
		else:
			return None

	def delete(self, position):
		if position < 0:
			return None

		try:
			return self.waiting.pop(position)
		except IndexError:
			return None

	def deleteall(self):
		self.waiting = []

	# playlist info

	def empty(self):
		return not bool(self.waiting)

	def len(self):
		return len(self.waiting)

	def get(self, i):
		try:
			return self.waiting[i]
		except IndexError:
			return None

	def items(self):
		return enumerate(self.waiting)

	def next(self):
		return self.waiting[0] if self.waiting else None

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
		"!queue <urls or ids> - add videos to the queue (alias: !q)\n"
		"!skip - skip the currently playing video (alias: !s)\n"
		"\n"
		"Advanced queue manipulation:\n"
		"!list - display a list of currently queued videos (alias: !l)\n"
		"!detail <indices> - show more details for videos in the queue (aliases: !info, !show)\n"
		"!delete <index> - deletes video at that index in the queue (aliases: !del, !d)\n"
		"!insert before|after <index> <urls or ids> - insert videos in the queue (aliases: !ins, !i)\n"
		"!deleteall - remove the whole queue (aliases: !dall, !d, !flush)\n"
		"\n"
		"Fun stuff:\n"
		"!dramaticskip - dramatic version of !skip (aliases: !dskip, !ds)\n"
		"!videoskip - play a short video before the next queued video starts (aliases: !vskip, !vs)\n"
	)

	SHORT_HELP = "Keeps track of the video queue. !q <link> to queue a new video."
	LONG_HELP = COMMANDS

	# Find the video id in a single argument
	VIDEO_ID_RE = r"[a-zA-Z0-9_-]{11}"
	YOUTUBE_RE = r"((https?://)?(www\.)?(youtube\.com/(watch\?v=|embed/)|youtu\.be/))?(" + VIDEO_ID_RE + ")"
	YOUTUBE_RE_GROUP = 6

	DEL_RE = r"(\d+)" # Per argument
	INS_RE = r"(before|after)\s+(\d+)\s+(.*)" # On the whole argstr

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
			await self.command_deleteall(room, message, command)

		await self.command_detail(room, message, command, argstr)

		await self.command_queue(room, message, command, argstr)
		await self.command_delete(room, message, command, argstr)
		await self.command_insert(room, message, command, argstr)

	async def find_videos(self, args):
		video_ids = []
		lines_parse_error = []
		for arg in args:
			if arg == "-id": continue
			match = re.match(self.YOUTUBE_RE, arg)
			if match:
				video_ids.append(match.group(self.YOUTUBE_RE_GROUP))
			else:
				lines_parse_error.append(f"Could not parse {arg!r}")

		videos = []
		lines_api_error = []
		video_lookup = await self.yt.get_videos(video_ids)
		for vid in video_ids:
			video = video_lookup.get(vid)
			if video:
				videos.append(video)
			else:
				lines_api_error.append(f"Video with id {vid} could not be accessed via the API")

		return videos, lines_parse_error, lines_api_error

	@yaboli.command("queue", "q")
	async def command_queue(self, room, message, argstr):
		args = self.parse_args(argstr)
		videos, lines_parse_error, lines_api_error = await self.find_videos(args)

		if not videos:
			text = "\n".join(lines_parse_error + lines_api_error)
			await room.send("ERROR: No valid videos specified\n" + text, message.mid)
			return

		lines = []
		for video in videos:
			position = self.playlist.insert(video, message.sender.nick)
			until = self.playlist.playtime_until(position)

			info = Playlist.format_list_entry(video, position, until)
			lines.extend(info)

		text = "\n".join(lines + lines_parse_error + lines_api_error)
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

	@yaboli.command("detail", "details", "info", "show")
	async def command_detail(self, room, message, argstr):
		indices = []
		lines_parse_error = []
		args = self.parse_args(argstr)
		for arg in args:
			match = re.match(r"\d+", arg)
			if match:
				indices.append(int(match.group(0)))
			else:
				lines_parse_error.append(f"Could not parse {arg!r}")

		videos = []
		lines_index_error = []
		for i in sorted(set(indices)):
			video = self.playlist.get(i)
			if video:
				videos.append(video)
			else:
				lines_index_error.append(f"No video at index {i}")

		if not videos:
			text = "\n".join(["ERROR: No valid indices given"] + lines_parse_error + lines_index_error)
			await room.send(text, message.mid)
			return

		lines = []
		for video, player in videos:
			info = []
			info.append(f"youtube.com/watch?v={video.id} {video.title!r}")
			info.append(f"Queued by {mention(player, ping=False)}")

			if video.blocked is not None:
				info.append(f"Blocked in {', '.join(video.blocked)}.")
			if video.allowed is not None:
				info.append(f"Only viewable in {', '.join(video.allowed)}.")

			lines.extend(info)
			lines.append("")

		text = "\n".join(lines + lines_parse_error + lines_index_error)
		await room.send(text, message.mid)

	@yaboli.command("delete", "del", "d")
	async def command_delete(self, room, message, argstr):
		indices = []
		lines_parse_error = []
		args = self.parse_args(argstr)
		for arg in args:
			match = re.fullmatch(self.DEL_RE, arg)
			if match:
				indices.append(int(match.group(1)))
			else:
				lines_parse_error.append(f"Could not parse {arg!r}")

		if not indices:
			text = "\n".join(["ERROR: No valid indices given"] + lines_parse_error)
			await room.send(text, message.mid)
			return

		lines = []
		lines_remove_error = []
		for i in reversed(sorted(set(indices))):
			success = self.playlist.delete(i)
			if success:
				video, _ = success
				lines.append(f"Removed {video.title!r}")
			else:
				lines_remove_error.append(f"No video at index {i}")

		text = "\n".join(lines + lines_parse_error + lines_remove_error)
		await room.send(text, message.mid)

	@yaboli.command("insert", "ins", "i")
	async def command_insert(self, room, message, argstr):
		match = re.fullmatch(self.INS_RE, argstr)
		if not match:
			await room.send("ERROR: Invalid command syntax", message.mid)
			return

		mode = match.group(1)
		before = int(match.group(2))
		args = self.parse_args(match.group(3))

		videos, lines_parse_error, lines_api_error = await self.find_videos(args)

		if not videos:
			text = "\n".join(lines_parse_error + lines_api_error)
			await room.send("ERROR: No valid videos specified\n" + text, message.mid)
			return

		if mode == "after":
			before += 1

		lines = []
		for video in videos:
			position = self.playlist.insert(video, message.sender.nick, before=before)
			before += 1
			until = self.playlist.playtime_until(position)

			info = Playlist.format_list_entry(video, position, until)
			lines.extend(info)

		text = "\n".join(lines + lines_parse_error + lines_api_error)
		await room.send(text, message.mid)
		self.playlist.play(room)

	@yaboli.command("deleteall", "dall", "da", "flush")
	async def command_deleteall(self, room, message):
		self.playlist.deleteall()
		await room.send("Queue deleted", message.mid)


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

