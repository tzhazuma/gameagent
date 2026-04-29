const fs = require("fs");
const express = require("express");
const bodyParser = require("body-parser");
const mineflayer = require("mineflayer");

const skills = require("./lib/skillLoader");
const { initCounter, getNextTime } = require("./lib/utils");
const obs = require("./lib/observation/base");
const OnChat = require("./lib/observation/onChat");
const OnError = require("./lib/observation/onError");
const { Voxels, BlockRecords } = require("./lib/observation/voxels");
const Status = require("./lib/observation/status");
const Inventory = require("./lib/observation/inventory");
const OnSave = require("./lib/observation/onSave");
const Chests = require("./lib/observation/chests");
const { plugin: tool } = require("mineflayer-tool");

let bot = null;

const app = express();

app.use(bodyParser.json({ limit: "50mb" }));
app.use(bodyParser.urlencoded({ limit: "50mb", extended: false }));

app.post("/start", (req, res) => {
    if (bot) onDisconnect("Restarting bot");
    bot = null;
    console.log(req.body);
    let responseSent = false;
    const startTimeout = setTimeout(() => {
        if (!responseSent) {
            responseSent = true;
            console.log("/start timeout waiting for bot spawn");
            try {
                if (bot) bot.end();
            } catch {}
            bot = null;
            res.status(504).json({ error: "Timed out waiting for bot spawn" });
        }
    }, 30000);
    bot = mineflayer.createBot({
        host: "localhost",
        port: req.body.port,
        username: "bot",
        auth: "offline",
        version: "1.19",
        disableChatSigning: true,
        checkTimeoutInterval: 60 * 60 * 1000,
    });
    const activeBot = bot;
    activeBot.connectionEnded = false;
    activeBot.once("error", onConnectionFailed);
    activeBot.on("end", () => {
        activeBot.connectionEnded = true;
        console.log("Bot connection ended");
    });

    // Event subscriptions
    activeBot.waitTicks = req.body.waitTicks;
    activeBot.globalTickCounter = 0;
    activeBot.stuckTickCounter = 0;
    activeBot.stuckPosList = [];
    activeBot.iron_pickaxe = false;

    activeBot.on("kicked", onDisconnect);

    // mounting will cause physicsTick to stop
    activeBot.on("mount", () => {
        activeBot.dismount();
    });

    activeBot.once("spawn", async () => {
        if (responseSent) return;
        console.log("bot spawn event fired");
        activeBot.removeListener("error", onConnectionFailed);
        activeBot.chat("/gamemode survival");
        let itemTicks = 1;
        if (req.body.reset === "hard") {
            activeBot.chat("/clear @s");
            activeBot.chat("/kill @s");
            const inventory = req.body.inventory ? req.body.inventory : {};
            const equipment = req.body.equipment
                ? req.body.equipment
                : [null, null, null, null, null, null];
            for (let key in inventory) {
                activeBot.chat(`/give @s minecraft:${key} ${inventory[key]}`);
                itemTicks += 1;
            }
            const equipmentNames = [
                "armor.head",
                "armor.chest",
                "armor.legs",
                "armor.feet",
                "weapon.mainhand",
                "weapon.offhand",
            ];
            for (let i = 0; i < 6; i++) {
                if (i === 4) continue;
                if (equipment[i]) {
                    activeBot.chat(
                        `/item replace entity @s ${equipmentNames[i]} with minecraft:${equipment[i]}`
                    );
                    itemTicks += 1;
                }
            }
        }

        if (req.body.position) {
            activeBot.chat(
                `/tp @s ${req.body.position.x} ${req.body.position.y} ${req.body.position.z}`
            );
        }

        // if iron_pickaxe is in bot's inventory
        if (
            activeBot.inventory.items().find((item) => item.name === "iron_pickaxe")
        ) {
            activeBot.iron_pickaxe = true;
        }

        const { pathfinder } = require("mineflayer-pathfinder");
        const tool = require("mineflayer-tool").plugin;
        const collectBlock = require("mineflayer-collectblock").plugin;
        const pvp = require("mineflayer-pvp").plugin;
        const minecraftHawkEye = require("minecrafthawkeye").default;
        console.log("loading plugins");
        activeBot.loadPlugin(pathfinder);
        activeBot.loadPlugin(tool);
        activeBot.loadPlugin(collectBlock);
        activeBot.loadPlugin(pvp);
        activeBot.loadPlugin(minecraftHawkEye);
        console.log("plugins loaded");

        // bot.collectBlock.movements.digCost = 0;
        // bot.collectBlock.movements.placeCost = 0;

        obs.inject(activeBot, [
            OnChat,
            OnError,
            Voxels,
            Status,
            Inventory,
            OnSave,
            Chests,
            BlockRecords,
        ]);
        console.log("observations injected");
        skills.inject(activeBot);
        console.log("skills injected");

        if (req.body.spread) {
            activeBot.chat(`/spreadplayers ~ ~ 0 300 under 80 false @s`);
            await activeBot.waitForTicks(activeBot.waitTicks);
        }

        await activeBot.waitForTicks(activeBot.waitTicks * itemTicks);
        console.log("about to observe bot state");
        if (!responseSent) {
            responseSent = true;
            clearTimeout(startTimeout);
            res.json(activeBot.observe());
            console.log("start response sent");
        }

        initCounter(activeBot);
        activeBot.chat("/gamerule keepInventory true");
        activeBot.chat("/gamerule doDaylightCycle false");
    });

    function onConnectionFailed(e) {
        console.log(e);
        clearTimeout(startTimeout);
        if (bot === activeBot) {
            bot = null;
        }
        if (!responseSent) {
            responseSent = true;
            res.status(400).json({ error: String(e?.message || e) });
        }
    }
    function onDisconnect(message) {
        if (activeBot.viewer) {
            activeBot.viewer.close();
        }
        activeBot.end();
        console.log(message);
        if (bot === activeBot) {
            bot = null;
        }
    }
});

app.post("/step", async (req, res) => {
    if (!bot || bot.connectionEnded) {
        res.status(400).json({ error: "Bot not spawned" });
        return;
    }
    // import useful package
    let response_sent = false;
    const activeBot = bot;
    function otherError(err) {
        console.log("Uncaught Error");
        console.log(err?.stack || err);
        if (!activeBot || activeBot.connectionEnded) {
            if (!response_sent) {
                response_sent = true;
                res.status(500).json({ error: String(err?.message || err) });
            }
            return;
        }
        activeBot.emit("error", handleError(err));
        activeBot.waitForTicks(activeBot.waitTicks).then(() => {
            if (!response_sent) {
                response_sent = true;
                res.json(activeBot.observe());
            }
        }).catch((waitErr) => {
            console.log(waitErr?.stack || waitErr);
            if (!response_sent) {
                response_sent = true;
                res.status(500).json({ error: String(err?.message || err) });
            }
        });
    }

    process.on("uncaughtException", otherError);

    const mcData = require("minecraft-data")(activeBot.version);
    mcData.itemsByName["leather_cap"] = mcData.itemsByName["leather_helmet"];
    mcData.itemsByName["leather_tunic"] =
        mcData.itemsByName["leather_chestplate"];
    mcData.itemsByName["leather_pants"] =
        mcData.itemsByName["leather_leggings"];
    mcData.itemsByName["leather_boots"] = mcData.itemsByName["leather_boots"];
    mcData.itemsByName["lapis_lazuli_ore"] = mcData.itemsByName["lapis_ore"];
    mcData.blocksByName["lapis_lazuli_ore"] = mcData.blocksByName["lapis_ore"];
    const {
        Movements,
        goals: {
            Goal,
            GoalBlock,
            GoalNear,
            GoalXZ,
            GoalNearXZ,
            GoalY,
            GoalGetToBlock,
            GoalLookAtBlock,
            GoalBreakBlock,
            GoalCompositeAny,
            GoalCompositeAll,
            GoalInvert,
            GoalFollow,
            GoalPlaceBlock,
        },
        pathfinder,
        Move,
        ComputedPath,
        PartiallyComputedPath,
        XZCoordinates,
        XYZCoordinates,
        SafeBlock,
        GoalPlaceBlockOptions,
    } = require("mineflayer-pathfinder");
    const { Vec3 } = require("vec3");

    // Set up pathfinder
    const movements = new Movements(activeBot, mcData);
    activeBot.pathfinder.setMovements(movements);

    activeBot.globalTickCounter = 0;
    activeBot.stuckTickCounter = 0;
    activeBot.stuckPosList = [];

    function onTick() {
        if (!activeBot || activeBot.connectionEnded) {
            return;
        }
        activeBot.globalTickCounter++;
        if (activeBot.pathfinder.isMoving()) {
            activeBot.stuckTickCounter++;
            if (activeBot.stuckTickCounter >= 100) {
                onStuck(1.5);
                activeBot.stuckTickCounter = 0;
            }
        }
    }

    activeBot.on("physicTick", onTick);

    // initialize fail count
    let _craftItemFailCount = 0;
    let _killMobFailCount = 0;
    let _mineBlockFailCount = 0;
    let _placeItemFailCount = 0;
    let _smeltItemFailCount = 0;

    // Retrieve array form post bod
    const code = req.body.code;
    const programs = req.body.programs;
    activeBot.cumulativeObs = [];
    await activeBot.waitForTicks(activeBot.waitTicks);
    const r = await evaluateCode(code, programs);
    process.off("uncaughtException", otherError);
    if (r !== "success") {
        activeBot.emit("error", handleError(r));
    }
    await returnItems();
    // wait for last message
    await activeBot.waitForTicks(activeBot.waitTicks);
    if (!response_sent) {
        response_sent = true;
        res.json(activeBot.observe());
    }
    activeBot.removeListener("physicTick", onTick);

    async function evaluateCode(code, programs) {
        // Echo the code produced for players to see it. Don't echo when the bot code is already producing dialog or it will double echo
        try {
            await eval("(async () => {" + programs + "\n" + code + "})()");
            return "success";
        } catch (err) {
            return err;
        }
    }

    function onStuck(posThreshold) {
        const currentPos = activeBot.entity.position;
        activeBot.stuckPosList.push(currentPos);

        // Check if the list is full
        if (activeBot.stuckPosList.length === 5) {
            const oldestPos = activeBot.stuckPosList[0];
            const posDifference = currentPos.distanceTo(oldestPos);

            if (posDifference < posThreshold) {
                teleportBot(); // execute the function
            }

            // Remove the oldest time from the list
            activeBot.stuckPosList.shift();
        }
    }

    function teleportBot() {
        const blocks = activeBot.findBlocks({
            matching: (block) => {
                return block.type === 0;
            },
            maxDistance: 1,
            count: 27,
        });

        if (blocks.length > 0) {
            const randomIndex = Math.floor(Math.random() * blocks.length);
            const block = blocks[randomIndex];
            activeBot.chat(`/tp @s ${block.x} ${block.y} ${block.z}`);
        } else {
            activeBot.chat("/tp @s ~ ~1.25 ~");
        }
    }

    function returnItems() {
        activeBot.chat("/gamerule doTileDrops false");
        const crafting_table = activeBot.findBlock({
            matching: mcData.blocksByName.crafting_table.id,
            maxDistance: 128,
        });
        if (crafting_table) {
            activeBot.chat(
                `/setblock ${crafting_table.position.x} ${crafting_table.position.y} ${crafting_table.position.z} air destroy`
            );
            activeBot.chat("/give @s crafting_table");
        }
        const furnace = activeBot.findBlock({
            matching: mcData.blocksByName.furnace.id,
            maxDistance: 128,
        });
        if (furnace) {
            activeBot.chat(
                `/setblock ${furnace.position.x} ${furnace.position.y} ${furnace.position.z} air destroy`
            );
            activeBot.chat("/give @s furnace");
        }
        if (activeBot.inventoryUsed() >= 32) {
            // if chest is not in bot's inventory
            if (!activeBot.inventory.items().find((item) => item.name === "chest")) {
                activeBot.chat("/give @s chest");
            }
        }
        // if iron_pickaxe not in bot's inventory and bot.iron_pickaxe
        if (
            activeBot.iron_pickaxe &&
            !activeBot.inventory.items().find((item) => item.name === "iron_pickaxe")
        ) {
            activeBot.chat("/give @s iron_pickaxe");
        }
        activeBot.chat("/gamerule doTileDrops true");
    }

    function handleError(err) {
        let stack = err.stack;
        if (!stack) {
            return err;
        }
        console.log(stack);
        const final_line = stack.split("\n")[1];
        const regex = /<anonymous>:(\d+):\d+\)/;

        const programs_length = programs.split("\n").length;
        let match_line = null;
        for (const line of stack.split("\n")) {
            const match = regex.exec(line);
            if (match) {
                const line_num = parseInt(match[1]);
                if (line_num >= programs_length) {
                    match_line = line_num - programs_length;
                    break;
                }
            }
        }
        if (!match_line) {
            return err.message;
        }
        let f_line = final_line.match(
            /\((?<file>.*):(?<line>\d+):(?<pos>\d+)\)/
        );
        if (f_line && f_line.groups && fs.existsSync(f_line.groups.file)) {
            const { file, line, pos } = f_line.groups;
            const f = fs.readFileSync(file, "utf8").split("\n");
            // let filename = file.match(/(?<=node_modules\\)(.*)/)[1];
            let source = file + `:${line}\n${f[line - 1].trim()}\n `;

            const code_source =
                "at " +
                code.split("\n")[match_line - 1].trim() +
                " in your code";
            return source + err.message + "\n" + code_source;
        } else if (
            f_line &&
            f_line.groups &&
            f_line.groups.file.includes("<anonymous>")
        ) {
            const { file, line, pos } = f_line.groups;
            let source =
                "Your code" +
                `:${match_line}\n${code.split("\n")[match_line - 1].trim()}\n `;
            let code_source = "";
            if (line < programs_length) {
                source =
                    "In your program code: " +
                    programs.split("\n")[line - 1].trim() +
                    "\n";
                code_source = `at line ${match_line}:${code
                    .split("\n")
                    [match_line - 1].trim()} in your code`;
            }
            return source + err.message + "\n" + code_source;
        }
        return err.message;
    }
});

app.post("/stop", (req, res) => {
    if (bot) {
        bot.end();
        bot = null;
    }
    res.json({
        message: "Bot stopped",
    });
});

app.post("/pause", (req, res) => {
    if (!bot || bot.connectionEnded) {
        res.status(400).json({ error: "Bot not spawned" });
        return;
    }
    bot.chat("/pause");
    bot.waitForTicks(bot.waitTicks).then(() => {
        res.json({ message: "Success" });
    });
});

// Server listening to PORT 3000

const DEFAULT_PORT = 3000;
const PORT = process.argv[2] || DEFAULT_PORT;
app.listen(PORT, () => {
    console.log(`Server started on port ${PORT}`);
});
