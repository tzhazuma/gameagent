const EventEmitter = require("events");
const express = require("express");
const { Vec3 } = require("vec3");

const { setupRoutes } = require("prismarine-viewer/lib/common");
const { WorldView } = require("prismarine-viewer").viewer;

const CAMERA_MODES = new Set(["orbit", "first-person", "close-follow"]);
const VIEWER_PLAYER_HEIGHT = 1.6;
const FOLLOW_LOOK_AHEAD = 3.6;
const FOLLOW_CLEARANCE = 0.85;
const FOLLOW_FOCUS_CLEARANCE = 0.25;
const FOLLOW_MIN_CAMERA_DISTANCE = 1.8;
const FOLLOW_MIN_FALLBACK_LOOK_Y = -0.12;
const FOLLOW_MAX_FALLBACK_LOOK_Y = 0.18;
const FOLLOW_PREFERRED_CAMERA_DISTANCE = 2.9;
const FOLLOW_TARGET_CAMERA_HEIGHT = 1.55;
const FOLLOW_MAX_CAMERA_HEIGHT = 1.85;
const FOLLOW_CANDIDATES = [
    { back: 2.8, side: 1.25, up: 0.1, preference: 0.24 },
    { back: 2.8, side: -1.25, up: 0.1, preference: 0.23 },
    { back: 2.5, side: 0.85, up: 0, preference: 0.18 },
    { back: 2.5, side: -0.85, up: 0, preference: 0.17 },
    { back: 3.1, side: 0.95, up: -0.05, preference: 0.1 },
    { back: 3.1, side: -0.95, up: -0.05, preference: 0.09 },
    { back: 2.3, side: 0, up: -0.15, preference: 0.03 },
    { back: 2.1, side: 0.55, up: -0.2, preference: -0.01 },
    { back: 2.1, side: -0.55, up: -0.2, preference: -0.02 },
];
const FOLLOW_VOLUME_SAMPLE_OFFSETS = [
    new Vec3(0, 0, 0),
    new Vec3(0, 0.45, 0),
    new Vec3(0, -0.45, 0),
    new Vec3(0.45, 0, 0),
    new Vec3(-0.45, 0, 0),
    new Vec3(0, 0, 0.45),
    new Vec3(0, 0, -0.45),
    new Vec3(0.35, 0.25, 0.35),
    new Vec3(-0.35, 0.25, 0.35),
    new Vec3(0.35, 0.25, -0.35),
    new Vec3(-0.35, 0.25, -0.35),
];

function vectorLength(vector) {
    return Math.sqrt((vector.x ** 2) + (vector.y ** 2) + (vector.z ** 2));
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function getViewDirection(yaw, pitch) {
    const cosPitch = Math.cos(pitch);
    return new Vec3(
        -Math.sin(yaw) * cosPitch,
        Math.sin(pitch),
        -Math.cos(yaw) * cosPitch
    );
}

function getHorizontalViewDirection(yaw) {
    return new Vec3(-Math.sin(yaw), 0, -Math.cos(yaw));
}

function traceSightLine(bot, start, end, clearance = FOLLOW_CLEARANCE) {
    const offset = end.minus(start);
    const desiredDistance = vectorLength(offset);
    if (desiredDistance <= 0.001) {
        return {
            start,
            direction: new Vec3(0, 0, 0),
            desiredDistance,
            clearDistance: 0,
            clearRatio: 0,
        };
    }

    const direction = offset.scaled(1 / desiredDistance);
    const occlusion = bot.world.raycast(start, direction, desiredDistance);
    const hitDistance = occlusion?.intersect ? start.distanceTo(occlusion.intersect) : desiredDistance;
    const clearDistance = Math.max(0, hitDistance - clearance);

    return {
        start,
        direction,
        desiredDistance,
        clearDistance,
        clearRatio: clearDistance / desiredDistance,
    };
}

function getBlockAt(bot, position) {
    return bot.blockAt(position.floored());
}

function isCameraObstacle(block) {
    return block && block.boundingBox && block.boundingBox !== "empty";
}

function scoreCameraVolume(bot, position) {
    let score = 0;
    let occupiedSamples = 0;
    let foliageSamples = 0;

    for (const offset of FOLLOW_VOLUME_SAMPLE_OFFSETS) {
        const block = getBlockAt(bot, position.plus(offset));
        if (!isCameraObstacle(block)) {
            score += 1;
            continue;
        }

        occupiedSamples += 1;
        if (block.name && block.name.includes("leaves")) {
            foliageSamples += 1;
            score -= 2.5;
            continue;
        }

        score -= block.transparent ? 1.5 : 4;
    }

    return { score, occupiedSamples, foliageSamples };
}

function getFocusTarget(anchor, forward) {
    const direction = new Vec3(
        forward.x,
        clamp(forward.y, FOLLOW_MIN_FALLBACK_LOOK_Y, FOLLOW_MAX_FALLBACK_LOOK_Y),
        forward.z
    );
    const directionLength = vectorLength(direction);
    const lookDirection = directionLength > 0.001
        ? direction.scaled(1 / directionLength)
        : new Vec3(0, 0, -1);
    return anchor.plus(lookDirection.scaled(FOLLOW_LOOK_AHEAD));
}

function getFollowCamera(bot) {
    const anchor = bot.entity.position.offset(0, VIEWER_PLAYER_HEIGHT, 0);
    const forward = getViewDirection(bot.entity.yaw, bot.entity.pitch);
    const horizontalForward = getHorizontalViewDirection(bot.entity.yaw);
    const right = new Vec3(-horizontalForward.z, 0, horizontalForward.x);
    const lookTarget = getFocusTarget(anchor, forward);

    let bestCamera = null;
    for (const candidate of FOLLOW_CANDIDATES) {
        const desiredEye = anchor
            .plus(horizontalForward.scaled(-candidate.back))
            .plus(right.scaled(candidate.side))
            .offset(0, candidate.up, 0);
        const anchorSight = traceSightLine(bot, anchor, desiredEye);
        const eye = desiredEye;
        const distanceFromAnchor = anchor.distanceTo(eye);
        if (distanceFromAnchor < FOLLOW_MIN_CAMERA_DISTANCE) {
            continue;
        }

        const cameraVolume = scoreCameraVolume(bot, eye);
        const targetSight = traceSightLine(bot, eye, lookTarget, FOLLOW_FOCUS_CLEARANCE);
        const distanceToTarget = eye.distanceTo(lookTarget);
        const cameraHeight = eye.y - bot.entity.position.y;
        const score = (anchorSight.clearRatio * 60)
            + (targetSight.clearRatio * 160)
            + (cameraVolume.score * 12)
            - (Math.abs(distanceFromAnchor - FOLLOW_PREFERRED_CAMERA_DISTANCE) * 12)
            - (Math.max(0, 2.8 - distanceToTarget) * 24)
            - (Math.abs(cameraHeight - FOLLOW_TARGET_CAMERA_HEIGHT) * 36)
            - (Math.max(0, cameraHeight - FOLLOW_MAX_CAMERA_HEIGHT) * 140)
            - (Math.abs(candidate.side) * 2)
            - (cameraVolume.occupiedSamples * 18)
            - (cameraVolume.foliageSamples * 44)
            - (anchorSight.clearRatio < 0.45 ? (0.45 - anchorSight.clearRatio) * 160 : 0)
            - (targetSight.clearRatio < 0.7 ? (0.7 - targetSight.clearRatio) * 220 : 0)
            + candidate.preference;

        if (!bestCamera || score > bestCamera.score) {
            bestCamera = {
                eye,
                score,
                distanceFromAnchor,
                targetSightClearRatio: targetSight.clearRatio,
                occupiedSamples: cameraVolume.occupiedSamples,
                foliageSamples: cameraVolume.foliageSamples,
            };
        }
    }

    if (!bestCamera) {
        return null;
    }

    const position = bestCamera.eye;
    const lookVector = lookTarget.minus(position);
    const horizontalDistance = Math.sqrt((lookVector.x ** 2) + (lookVector.z ** 2));

    return {
        pos: position.offset(0, -VIEWER_PLAYER_HEIGHT, 0),
        yaw: Math.atan2(-lookVector.x, -lookVector.z),
        pitch: Math.atan2(lookVector.y, horizontalDistance),
    };
}

function resolveCameraMode(cameraMode, firstPerson) {
    if (CAMERA_MODES.has(cameraMode)) {
        return cameraMode;
    }
    return firstPerson ? "first-person" : "orbit";
}

function createSocketEmitter(socket, emitEntities) {
    return {
        emit(event, payload) {
            if (event === "entity" && !emitEntities) {
                return false;
            }
            socket.emit(event, payload);
            return true;
        },
        on(event, listener) {
            socket.on(event, listener);
        },
    };
}

function buildCameraPacket(bot, cameraMode) {
    const packet = {
        pos: bot.entity.position,
        addMesh: cameraMode === "orbit",
    };

    if (cameraMode === "orbit") {
        return packet;
    }

    packet.yaw = bot.entity.yaw;
    packet.pitch = bot.entity.pitch;

    if (cameraMode === "close-follow") {
        const followCamera = getFollowCamera(bot);
        if (followCamera) {
            packet.pos = followCamera.pos;
            packet.yaw = followCamera.yaw;
            packet.pitch = followCamera.pitch;
        }
    }

    return packet;
}

module.exports = (bot, { viewDistance = 6, firstPerson = false, cameraMode = "orbit", port = 3000, prefix = "" }) => {
    const app = express();
    const http = require("http").createServer(app);
    const io = require("socket.io")(http, { path: prefix + "/socket.io" });

    setupRoutes(app, prefix);

    const sockets = [];
    const primitives = {};
    const resolvedCameraMode = resolveCameraMode(cameraMode, firstPerson);
    const emitEntities = resolvedCameraMode === "orbit";

    bot.viewer = new EventEmitter();

    bot.viewer.erase = (id) => {
        delete primitives[id];
        for (const socket of sockets) {
            socket.emit("primitive", { id });
        }
    };

    bot.viewer.drawBoxGrid = (id, start, end, color = "aqua") => {
        primitives[id] = { type: "boxgrid", id, start, end, color };
        for (const socket of sockets) {
            socket.emit("primitive", primitives[id]);
        }
    };

    bot.viewer.drawLine = (id, points, color = 0xff0000) => {
        primitives[id] = { type: "line", id, points, color };
        for (const socket of sockets) {
            socket.emit("primitive", primitives[id]);
        }
    };

    bot.viewer.drawPoints = (id, points, color = 0xff0000, size = 5) => {
        primitives[id] = { type: "points", id, points, color, size };
        for (const socket of sockets) {
            socket.emit("primitive", primitives[id]);
        }
    };

    io.on("connection", (socket) => {
        socket.emit("version", bot.version);
        sockets.push(socket);

        const socketEmitter = createSocketEmitter(socket, emitEntities);
        const worldView = new WorldView(bot.world, viewDistance, bot.entity.position, socketEmitter);
        worldView.init(bot.entity.position);

        worldView.on("blockClicked", (block, face, button) => {
            bot.viewer.emit("blockClicked", block, face, button);
        });

        for (const id in primitives) {
            socket.emit("primitive", primitives[id]);
        }

        function botPosition() {
            socket.emit("position", buildCameraPacket(bot, resolvedCameraMode));
            worldView.updatePosition(bot.entity.position);
        }

        bot.on("move", botPosition);
        worldView.listenToBot(bot);
        botPosition();

        socket.on("disconnect", () => {
            bot.removeListener("move", botPosition);
            worldView.removeListenersFromBot(bot);
            sockets.splice(sockets.indexOf(socket), 1);
        });
    });

    http.listen(port, () => {
        console.log(`Prismarine viewer web server running on *:${port}`);
    });

    bot.viewer.close = () => {
        http.close();
        for (const socket of sockets) {
            socket.disconnect();
        }
    };
};
