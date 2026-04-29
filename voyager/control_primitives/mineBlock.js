async function mineBlock(bot, name, count = 1) {
    // return if name is not string
    if (typeof name !== "string") {
        throw new Error(`name for mineBlock must be a string`);
    }
    if (typeof count !== "number") {
        throw new Error(`count for mineBlock must be a number`);
    }
    const blockByName = mcData.blocksByName[name];
    if (!blockByName) {
        throw new Error(`No block named ${name}`);
    }
    const blocks = bot.findBlocks({
        matching: [blockByName.id],
        maxDistance: 32,
        count: 1024,
    });
    if (blocks.length === 0) {
        bot.chat(`No ${name} nearby, please explore first`);
        _mineBlockFailCount++;
        if (_mineBlockFailCount > 10) {
            throw new Error(
                "mineBlock failed too many times, make sure you explore before calling mineBlock"
            );
        }
        return;
    }
    const targets = [];
    for (let i = 0; i < blocks.length; i++) {
        targets.push(bot.blockAt(blocks[i]));
    }
    const itemByName = mcData.itemsByName[name];
    const itemId = itemByName ? itemByName.id : null;
    const beforeCount = itemId
        ? bot.inventory.items().reduce((total, item) => {
              return item.type === itemId ? total + item.count : total;
          }, 0)
        : 0;

    const countItems = () => {
        if (!itemId) return 0;
        return bot.inventory.items().reduce((total, item) => {
            return item.type === itemId ? total + item.count : total;
        }, 0);
    };

    const collectNearbyDrops = async () => {
        const drops = Object.values(bot.entities).filter((entity) => {
            return (
                entity.name === "item" &&
                entity.position.distanceTo(bot.entity.position) <= 8
            );
        });
        for (const drop of drops) {
            try {
                await bot.collectBlock.collect(drop, {
                    ignoreNoPath: true,
                    count: 1,
                });
            } catch {
                // Ignore unreachable or already-despawned drops.
            }
            if (countItems() >= beforeCount + count) {
                return;
            }
        }
    };

    await bot.collectBlock.collect(targets, {
        ignoreNoPath: true,
        count: count,
    });

    if (itemId) {
        let remainingTicks = 40;
        while (remainingTicks > 0) {
            const afterCount = countItems();
            if (afterCount >= beforeCount + count) {
                break;
            }
            await bot.waitForTicks(1);
            remainingTicks -= 1;
        }

        if (countItems() < beforeCount + count) {
            await collectNearbyDrops();
        }

        let settleTicks = 20;
        while (countItems() < beforeCount + count && settleTicks > 0) {
            await bot.waitForTicks(1);
            settleTicks -= 1;
        }
    }

    bot.save(`${name}_mined`);
}
