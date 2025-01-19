from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import join_room, leave_room, send, SocketIO
from flask_session import Session
import random
from string import ascii_uppercase
from flask_pymongo import PyMongo
from datetime import datetime
import pytz


app = Flask(__name__)

app.config["SECRET_KEY"] = "KEY"
app.config["MONGO_URI"] = "mongodb://localhost:27017/chat_app"

mongo = PyMongo(app)

app.config["SESSION_TYPE"] = "mongodb"
app.config["SESSION_MONGODB"] = mongo.cx
app.config["SESSION_MONGODB_DB"] = "chat_app"
app.config["SESSION_MONGODB_COLLECT"] = "sessions"
app.config["SESSION_PERMANENT"] = False

socketio = SocketIO(app, cors_allowed_origins="*")
Session((app))

rooms_collection = mongo.db.rooms
messages_collection = mongo.db.messages


def generate_unique_code(length):
    while True:
        code = "".join(random.choice(ascii_uppercase) for _ in range(length))
        if not rooms_collection.find_one({"roomId": code}):
            return code


@app.route("/", methods=["GET", "POST"])
def home():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        if not name:
            return render_template(
                "home.html", error="Please enter a name.", code=code, name=name
            )

        if join != False and not code:
            return render_template(
                "home.html", error="Please enter a room code.", code=code, name=name
            )

        room = code
        if create != False:
            room = generate_unique_code(4)
            rooms_collection.insert_one(
                {"roomId": room, "members": [], "activeMembers": 0}
            )
            messages_data = {"roomId": room, "messages": []}
            messages_collection.insert_one(messages_data)
        elif not rooms_collection.find_one({"roomId": room}):
            return render_template(
                "home.html", error="Room does not exist.", code=code, name=name
            )

        session["room"] = room
        session["name"] = name
        return redirect(url_for("room"))

    return render_template("home.html")


@app.route("/room")
def room():
    room = session.get("room")
    name = session.get("name")

    if not room or not name:
        return redirect(url_for("home"))

    room_data = rooms_collection.find_one({"roomId": room})
    if not room_data:
        return redirect(url_for("home"))

    messages_data = messages_collection.find_one({"roomId": room})
    messages = messages_data["messages"] if messages_data else []

    return render_template("room.html", code=room, messages=messages)


@socketio.on("message")
def message(data):
    room = session.get("room")
    name = session.get("name")

    if not room or not name:
        return

    utc_time = datetime.utcnow().replace(tzinfo=pytz.utc)
    ist_time = utc_time.astimezone(pytz.timezone("Asia/Kolkata"))

    content = {
        "name": session.get("name"),
        "message": data["data"],
        "timestamp": ist_time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    send(content, to=room)
    messages_collection.update_one({"roomId": room}, {"$push": {"messages": content}})

    print(f"{session.get('name')} said {data['data']} at {content['timestamp']} ")


@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")

    if not room or not name:
        return

    join_room(room)
    send({"name": name, "message": "has entered the room"}, to=room)
    rooms_collection.update_one(
        {"roomId": room},
        {"$addToSet": {"members": name}, "$inc": {"activeMembers": 1}},
    )
    print(f"{name} joined room {room}, {datetime.utcnow()} ")


@socketio.on("disconnected")
def disconnect():
    room = session.get("room")
    name = session.get("name")

    if not room or not name:
        return

    leave_room(room)
    rooms_collection.update_one(
        {"roomId": room}, {"$pull": {"members": name}, "$inc": {"activeMembers": -1}}
    )

    room_data = rooms_collection.find_one({"roomId": room})
    if room_data and room_data["activeMembers"] <= 0:
        rooms_collection.delete_one({"roomId": room})
        messages_collection.delete_one({"roomId": room})

    send({"name": name, "message": "has left the room"}, to=room)
    print(f"{name} has left the room {room}, {datetime.utcnow()}")


if __name__ == "__main__":
    socketio.run(app, debug=True)
