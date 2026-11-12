"""macOS media controls for the player: Control Center's Now Playing and the media keys.

The player registers as the "now playing" app while it has something to play, so the
keyboard's play/pause and skip keys, headphone buttons, and Control Center control
Speak. When the queue empties it lets go, and the keys return to Music and the rest.

Runs in the player (runtime Python with PyObjC). The command mapping and the Now Playing
fields are plain functions, testable without PyObjC.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional

SKIP_SECONDS = 5
RELEASE_AFTER_PAUSE = 300  # seconds paused before the media keys go back to other players


def handle_command(speaker, name: str, position: Optional[float] = None) -> bool:
    """Apply a media command to the player; False when nothing is playing."""
    if not speaker.busy():
        return False
    if name == "toggle":
        speaker.set_paused(None)
    elif name == "play":
        speaker.set_paused(False)
    elif name == "pause":
        speaker.set_paused(True)
    elif name == "next":
        speaker.skip()
    elif name == "previous":
        speaker.seek(-1e9)  # back to the start of this response, as players do
    elif name == "forward":
        speaker.seek(SKIP_SECONDS)
    elif name == "back":
        speaker.seek(-SKIP_SECONDS)
    elif name == "position" and position is not None:
        speaker.seek(position - speaker.snapshot().get("position", 0))
    else:
        return False
    return True


def now_playing(snapshot: dict) -> Optional[Dict[str, object]]:
    """The Now Playing fields for a player snapshot, or None when idle."""
    state = snapshot.get("state", "idle")
    if state == "idle" or (state == "paused" and float(snapshot.get("paused_seconds") or 0) > RELEASE_AFTER_PAUSE):
        return None  # idle, or paused long enough that the keys should control Music and the rest again
    title = snapshot.get("title") or "Speak"
    agent, _, place = title.partition(" in ")
    return {
        "title": title if not place else f"{agent} · {place}",
        "artist": "Speak",
        "duration": float(snapshot.get("duration") or 0),
        "elapsed": float(snapshot.get("position") or 0),
        "rate": 1.0 if state == "playing" else 0.0,
        "paused": state == "paused",
    }


class MediaControls:
    """Owns the PyObjC side: registration, updates, and pumping the run loop."""

    def __init__(self, speaker, log: Callable[[str], None]):
        self.speaker = speaker
        self.log = log
        self.enabled = False
        self.registered = False
        self.last: Optional[Dict[str, object]] = None
        self.last_push = 0.0
        self.mp = None
        try:
            import AppKit
            import Foundation
            import MediaPlayer

            self.mp, self.foundation = MediaPlayer, Foundation
            app = AppKit.NSApplication.sharedApplication()
            app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # no Dock icon
        except Exception as error:  # PyObjC missing or no window server: keys simply don't work
            self.log(f"media controls unavailable: {error!r}")

    @property
    def available(self) -> bool:
        return self.mp is not None

    def _commands(self):
        center = self.mp.MPRemoteCommandCenter.sharedCommandCenter()
        return {
            "toggle": center.togglePlayPauseCommand(), "play": center.playCommand(), "pause": center.pauseCommand(),
            "next": center.nextTrackCommand(), "previous": center.previousTrackCommand(),
            "forward": center.skipForwardCommand(), "back": center.skipBackwardCommand(),
            "position": center.changePlaybackPositionCommand(),
        }

    def _register(self) -> None:
        if self.registered:
            return
        success, failed = self.mp.MPRemoteCommandHandlerStatusSuccess, self.mp.MPRemoteCommandHandlerStatusCommandFailed
        for name, command in self._commands().items():
            if name in ("forward", "back"):
                command.setPreferredIntervals_([SKIP_SECONDS])

            def handler(event, name=name):
                position = event.positionTime() if name == "position" else None
                ok = handle_command(self.speaker, name, position)
                self.last = None  # push fresh info right away
                return success if ok else failed

            command.addTargetWithHandler_(handler)
        self.registered = True

    def _set_commands_enabled(self, enabled: bool) -> None:
        for command in self._commands().values():
            command.setEnabled_(enabled)

    def update(self, snapshot: dict, enabled: bool) -> None:
        """Mirror the player into Now Playing; let go when idle or turned off."""
        if not self.available:
            return
        fields = now_playing(snapshot) if enabled else None
        center = self.mp.MPNowPlayingInfoCenter.defaultCenter()
        if fields is None:
            if self.last is not None or self.enabled:
                center.setNowPlayingInfo_(None)
                center.setPlaybackState_(self.mp.MPNowPlayingPlaybackStateStopped)
                if self.registered:
                    self._set_commands_enabled(False)
            self.last, self.enabled = None, False
            return
        if not self.enabled:
            self._register()
            self._set_commands_enabled(True)
            self.enabled = True
        # The system extrapolates elapsed time from the rate; push on changes and every few seconds.
        changed = self.last is None or any(self.last[key] != fields[key] for key in ("title", "rate", "paused")) \
            or abs(float(self.last["duration"]) - float(fields["duration"])) > 1
        if not changed and time.time() - self.last_push < 5:
            return
        mp = self.mp
        center.setNowPlayingInfo_({
            mp.MPMediaItemPropertyTitle: fields["title"],
            mp.MPMediaItemPropertyArtist: fields["artist"],
            mp.MPMediaItemPropertyPlaybackDuration: fields["duration"],
            mp.MPNowPlayingInfoPropertyElapsedPlaybackTime: fields["elapsed"],
            mp.MPNowPlayingInfoPropertyPlaybackRate: fields["rate"],
        })
        center.setPlaybackState_(mp.MPNowPlayingPlaybackStatePaused if fields["paused"] else mp.MPNowPlayingPlaybackStatePlaying)
        self.last, self.last_push = fields, time.time()

    def wait(self, seconds: float) -> None:
        """Sleep while letting macOS deliver media commands (they arrive on the main run loop)."""
        if not self.available:
            time.sleep(seconds)
            return
        loop = self.foundation.NSRunLoop.currentRunLoop()
        loop.runUntilDate_(self.foundation.NSDate.dateWithTimeIntervalSinceNow_(seconds))

    def close(self) -> None:
        if self.available:
            self.update({"state": "idle"}, enabled=False)
