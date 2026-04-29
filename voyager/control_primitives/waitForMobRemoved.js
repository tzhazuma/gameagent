function formatFailureReason(reason) {
    if (!reason) {
        return "connection ended";
    }
    if (reason instanceof Error) {
        return reason.message;
    }
    if (typeof reason === "string") {
        return reason;
    }
    try {
        return JSON.stringify(reason);
    } catch {
        return String(reason);
    }
}


function waitForMobRemoved(bot, entity, timeout = 300) {
    return new Promise((resolve, reject) => {
        let settled = false;
        let success = false;
        let droppedItem = null;
        let successTimeoutId = null;

        function cleanup() {
            clearTimeout(timeoutId);
            if (successTimeoutId) {
                clearTimeout(successTimeoutId);
            }
            bot.removeListener("entityGone", onEntityGone);
            bot.removeListener("stoppedAttacking", onStoppedAttacking);
            bot.removeListener("itemDrop", onItemDrop);
            bot.removeListener("end", onDisconnected);
            bot.removeListener("kicked", onKicked);
        }

        function finish(error = null) {
            if (settled) {
                return;
            }
            settled = true;
            cleanup();
            if (error) {
                reject(error);
            } else {
                resolve(droppedItem);
            }
        }

        function stopAttacking() {
            try {
                const stopResult = bot.pvp?.stop?.();
                if (stopResult && typeof stopResult.catch === "function") {
                    stopResult.catch(() => {});
                }
            } catch {}
        }

        // Set up timeout
        const timeoutId = setTimeout(() => {
            stopAttacking();
            finish(new Error(`Timed out trying to kill ${entity.name}.`));
        }, timeout * 1000);

        // Function to handle entityRemoved event
        function onEntityGone(e) {
            if (e !== entity || settled) {
                return;
            }
            success = true;
            clearTimeout(timeoutId);
            bot.chat(`Killed ${entity.name}!`);
            stopAttacking();
            successTimeoutId = setTimeout(() => finish(), 1000);
        }

        function onItemDrop(item) {
            if (entity.position.distanceTo(item.position) <= 1) {
                droppedItem = item;
            }
        }

        function onStoppedAttacking() {
            if (!success) {
                finish(new Error(`Failed to kill ${entity.name}.`));
            } else {
                finish();
            }
        }

        function onDisconnected(reason) {
            stopAttacking();
            if (success) {
                finish();
                return;
            }
            finish(
                new Error(
                    `Bot disconnected while killing ${entity.name}: ${formatFailureReason(reason)}.`
                )
            );
        }

        function onKicked(reason) {
            onDisconnected(reason);
        }

        // Listen for entityRemoved event
        bot.on("entityGone", onEntityGone);
        bot.on("stoppedAttacking", onStoppedAttacking);
        bot.on("itemDrop", onItemDrop);
        bot.on("end", onDisconnected);
        bot.on("kicked", onKicked);
    });
}


function waitForMobShot(bot, entity, timeout = 300) {
    return new Promise((resolve, reject) => {
        let settled = false;
        let success = false;
        let droppedItem = null;
        let successTimeoutId = null;

        function cleanup() {
            clearTimeout(timeoutId);
            if (successTimeoutId) {
                clearTimeout(successTimeoutId);
            }
            bot.removeListener("entityGone", onEntityGone);
            bot.removeListener("auto_shot_stopped", onAutoShotStopped);
            bot.removeListener("itemDrop", onItemDrop);
            bot.removeListener("end", onDisconnected);
            bot.removeListener("kicked", onKicked);
        }

        function finish(error = null) {
            if (settled) {
                return;
            }
            settled = true;
            cleanup();
            if (error) {
                reject(error);
            } else {
                resolve(droppedItem);
            }
        }

        function stopShooting() {
            try {
                bot.hawkEye?.stop?.();
            } catch {}
        }

        // Set up timeout
        const timeoutId = setTimeout(() => {
            stopShooting();
            finish(new Error(`Timed out trying to shoot ${entity.name}.`));
        }, timeout * 1000);

        // Function to handle entityRemoved event
        function onEntityGone(e) {
            if (e !== entity || settled) {
                return;
            }
            success = true;
            clearTimeout(timeoutId);
            bot.chat(`Shot ${entity.name}!`);
            stopShooting();
            successTimeoutId = setTimeout(() => finish(), 1000);
        }

        function onItemDrop(item) {
            if (entity.position.distanceTo(item.position) <= 1) {
                droppedItem = item;
            }
        }

        function onAutoShotStopped() {
            if (!success) {
                finish(new Error(`Failed to shoot ${entity.name}.`));
            } else {
                finish();
            }
        }

        function onDisconnected(reason) {
            stopShooting();
            if (success) {
                finish();
                return;
            }
            finish(
                new Error(
                    `Bot disconnected while shooting ${entity.name}: ${formatFailureReason(reason)}.`
                )
            );
        }

        function onKicked(reason) {
            onDisconnected(reason);
        }

        // Listen for entityRemoved event
        bot.on("entityGone", onEntityGone);
        bot.on("auto_shot_stopped", onAutoShotStopped);
        bot.on("itemDrop", onItemDrop);
        bot.on("end", onDisconnected);
        bot.on("kicked", onKicked);
    });
}
