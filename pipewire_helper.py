#!/usr/bin/python3
"""Portal-authorized PipeWire window capture; binary protocol for continuous_capture.py.

Run with Arch's system Python (which has python-dbus/python-gobject).
Stdout is reserved for READY/FRAME messages and frame bytes.
"""
import os
import re
import sys
import threading
import time

import dbus
import gi
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

DBusGMainLoop(set_as_default=True)
Gst.init(None)
loop = GLib.MainLoop()
bus = dbus.SessionBus()
portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
iface = "org.freedesktop.portal.ScreenCast"
sender = re.sub(r"\W", "_", bus.get_unique_name()[1:])
counter = 0
session = None
pipeline = None
latest = None
frame_lock = threading.Lock()
write_lock = threading.Lock()


def request(method, callback, *args, options=None):
    global counter
    counter += 1
    token = f"e7_{os.getpid()}_{counter}"
    path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    bus.add_signal_receiver(callback, signal_name="Response",
                            dbus_interface="org.freedesktop.portal.Request",
                            bus_name="org.freedesktop.portal.Desktop", path=path)
    values = dict(options or {})
    values["handle_token"] = token
    getattr(portal, method)(*args, dbus.Dictionary(values, signature="sv"), dbus_interface=iface)


def fail(reason):
    print(reason, file=sys.stderr, flush=True)
    loop.quit()


def on_sample(sink):
    global latest
    sample = sink.emit("pull-sample")
    if not sample:
        return Gst.FlowReturn.ERROR
    caps = sample.get_caps().get_structure(0)
    width, height = caps.get_value("width"), caps.get_value("height")
    buffer = sample.get_buffer()
    ok, data = buffer.map(Gst.MapFlags.READ)
    if not ok:
        return Gst.FlowReturn.ERROR
    try:
        # BGR rows may have GStreamer padding; repack to tightly packed bytes.
        stride = buffer.get_size() // height
        if stride < width * 3:
            return Gst.FlowReturn.ERROR
        packed = b"".join(bytes(data.data[row*stride:row*stride+width*3]) for row in range(height))
    finally:
        buffer.unmap(data)
    with frame_lock:
        latest = (width, height, packed, time.monotonic_ns())
    return Gst.FlowReturn.OK


def serve():
    while True:
        command = sys.stdin.buffer.readline()
        if not command or command.strip() == b"QUIT":
            GLib.idle_add(loop.quit)
            return
        if command.strip() != b"FRAME":
            continue
        with frame_lock:
            frame = latest
        with write_lock:
            if frame is None:
                sys.stdout.buffer.write(b"WAIT\n")
            else:
                width, height, data, stamp = frame
                sys.stdout.buffer.write(f"FRAME {width} {height} {len(data)} {stamp}\n".encode())
                sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


def started(response, results):
    global pipeline
    if response != 0:
        return fail(f"ScreenCast Start rejected: {response}")
    streams = results.get("streams", [])
    if len(streams) != 1:
        return fail(f"Expected exactly one selected stream, received {len(streams)}")
    node_id, _properties = streams[0]
    fd_obj = portal.OpenPipeWireRemote(session, dbus.Dictionary(signature="sv"), dbus_interface=iface)
    fd = fd_obj.take()
    pipeline = Gst.parse_launch(
        f"pipewiresrc fd={fd} path={int(node_id)} do-timestamp=true ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=frames emit-signals=true max-buffers=1 drop=true sync=false")
    pipeline.get_by_name("frames").connect("new-sample", on_sample)
    pipeline.set_state(Gst.State.PLAYING)
    sys.stdout.buffer.write(b"READY\n")
    sys.stdout.buffer.flush()
    threading.Thread(target=serve, daemon=True).start()


def selected(response, results):
    if response != 0:
        return fail(f"ScreenCast SelectSources rejected: {response}")
    request("Start", started, session, "")


def created(response, results):
    global session
    if response != 0:
        return fail(f"ScreenCast CreateSession rejected: {response}")
    session = results["session_handle"]
    # Window capture only: never accept an arbitrary monitor as a game frame.
    request("SelectSources", selected, session,
            options={"multiple": False, "types": dbus.UInt32(2),
                     "cursor_mode": dbus.UInt32(1)})


request("CreateSession", created, options={"session_handle_token": f"e7session_{os.getpid()}"})
try:
    loop.run()
finally:
    if pipeline:
        pipeline.set_state(Gst.State.NULL)
    if session:
        try:
            bus.get_object("org.freedesktop.portal.Desktop", session).Close(
                dbus_interface="org.freedesktop.portal.Session")
        except dbus.DBusException:
            pass
