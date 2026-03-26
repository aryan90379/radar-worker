const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);
const connectDB = require('./database');

// Models
const RadarQueue = require('./models/RadarQueue');
const BrandRadar = require('./models/BrandRadar');
const RadarPost = require('./models/RadarPost');
const RadarCollaboration = require('./models/RadarCollaboration');

const SLEEP_MS = 5000;

// Helper: Sleep function for pacing our scrapers
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// --- STAGE 1: Get the Profile and Base List of Posts ---
async function scrapeBrandFeed(username, targetPosts) {
    console.log(`\n📡 [STAGE 1] Sweeping feed for: @${username} (Target: ${targetPosts})`);
    try {
        // 🚀 CHANGED: Point explicitly to .venv python here as well to be safe
        const { stdout, stderr } = await execPromise(`./.venv/bin/python ig_scraper.py ${username} ${targetPosts}`, { maxBuffer: 1024 * 1024 * 50 });
        if (stderr && !stderr.includes("WARNING")) console.log(`[Feed Scraper Log]: ${stderr.trim()}`);
        return JSON.parse(stdout);
    } catch (error) {
        console.error(`❌ Feed Scrape Error for ${username}:`, error.message);
        throw error;
    }
}

// --- STAGE 2: Deep Scan a Single Post ---
async function scrapePostDetails(shortcode) {
    try {
        // 🚀 CHANGED: Point explicitly to .venv python and the correct script name
        const { stdout } = await execPromise(`./.venv/bin/python ig_scraper_reel.py ${shortcode}`, { maxBuffer: 1024 * 1024 * 10 });
        return JSON.parse(stdout);
    } catch (error) {
        // Expose the actual error so you aren't flying blind
        console.error(`⚠️ Deep Scan failed for ${shortcode}. Using fallback data. Reason: ${error.message.split('\n')[0]}`);
        return null; 
    }
}

// --- CORE: Process the Brand ---
async function processBrand(queueItem) {
    const { brandUsername, targetPosts } = queueItem;
    console.log(`\n⚙️ Processing Brand: @${brandUsername}`);

    queueItem.status = 'processing';
    queueItem.attempts += 1;
    await queueItem.save();

    try {
        let profile = null;
        let basicPosts = [];
        let scrapeAttempts = 0;
        const MAX_RETRIES = 15; // Prevent infinite loops if IG completely blocks us

        // 🚀 SMART RETRY LOOP
        while (scrapeAttempts < MAX_RETRIES) {
            scrapeAttempts++;
            try {
                const data = await scrapeBrandFeed(brandUsername, targetPosts);
                profile = data.profile;
                basicPosts = data.recentPosts || [];

                // Calculate required posts: 150, UNLESS the account has fewer than 150 posts in total!
                const requiredPosts = Math.min(144, profile.media_count || 204);

                if (basicPosts.length >= requiredPosts) {
                    console.log(`✅ Success: Fetched ${basicPosts.length} posts!`);
                    break; // Exit the retry loop
                } else {
                    console.log(`⚠️ Got ${basicPosts.length} posts, but need at least ${requiredPosts}. Retrying... (Attempt ${scrapeAttempts}/${MAX_RETRIES})`);
                    await sleep(6000); // Sleep 6 seconds before trying again to cool down proxy
                }
            } catch (err) {
                console.error(`⚠️ Scrape attempt ${scrapeAttempts} failed. Retrying...`);
                if (scrapeAttempts >= MAX_RETRIES) throw err;
                await sleep(6000);
            }
        }

        if (!basicPosts || basicPosts.length === 0) {
            throw new Error("No posts found after maximum retries.");
        }

        console.log(`\n🔍 [STAGE 2] Deep Scanning ${basicPosts.length} posts in PARALLEL CHUNKS...`);
        const enrichedPosts = [];
        
        // 🚀 PARALLEL CHUNKING: Process 8 posts at the same time to speed things up safely
        const CONCURRENCY_LIMIT = 8; 
        
        for (let i = 0; i < basicPosts.length; i += CONCURRENCY_LIMIT) {
            const chunk = basicPosts.slice(i, i + CONCURRENCY_LIMIT);
            const currentEnd = Math.min(i + CONCURRENCY_LIMIT, basicPosts.length);
            console.log(`⚡ Scanning batch ${i + 1} to ${currentEnd} of ${basicPosts.length}...`);
            
            // Map the chunk into an array of concurrent Promises
            const chunkPromises = chunk.map(async (post) => {
                const deepData = await scrapePostDetails(post.shortcode);
                if (deepData) {
                    return {
                        ...post,
                        like_count: deepData.likes > 0 ? deepData.likes : post.like_count,
                        comments_count: deepData.comments > 0 ? deepData.comments : post.comments_count,
                        play_count: deepData.plays > 0 ? deepData.plays : post.play_count,
                        caption: deepData.caption || post.caption,
                        media_url: deepData.video_url || deepData.image_url || post.media_url,
                        collaborators: deepData.collaborators || post.collaborators || [],
                        tagged_users: deepData.tagged_users || []
                    };
                }
                return post; // Fallback to basic data if it fails
            });

            // Wait for this entire batch of 8 to finish at the exact same time
            const resolvedChunk = await Promise.all(chunkPromises);
            enrichedPosts.push(...resolvedChunk);

            // Sleep 3.5 seconds between batches to let the proxies breathe and avoid 429 rate limits
            if (currentEnd < basicPosts.length) {
                await sleep(3500); 
            }
        }

        let totalLikes = 0, totalComments = 0, totalPlays = 0;
        let reelCount = 0, imageCount = 0;
        let collabStats = {}; 

        console.log(`\n💾 Saving ${enrichedPosts.length} enriched posts to database...`);
        
        // 2. Process and Save the Enriched Posts
        for (const post of enrichedPosts) {
            await RadarPost.findOneAndUpdate(
                { shortcode: post.shortcode },
                {
                    brandUsername,
                    mediaId: post.id,
                    type: post.media_type,
                    caption: post.caption,
                    mediaUrl: post.media_url,
                    permalink: post.permalink,
                    metrics: {
                        likes: post.like_count || 0,
                        comments: post.comments_count || 0,
                        plays: post.play_count || 0,
                        // 🚀 NEW: Virality Score = (likes + comments + (plays*0.1)) / followers
                        viralityScore: Number((((post.like_count || 0) + (post.comments_count || 0) + ((post.play_count || 0) * 0.1)) / (profile.followers_count || 1)).toFixed(4))
                    },
                    // 🚀 NEW: Content Intelligence Extraction
                    hashtags: (post.caption || '').match(/#[a-zA-Z0-9_]+/g) || [],
                    mentions: (post.caption || '').match(/@[a-zA-Z0-9_.]+/g) || [],
                    isCollaboration: (post.collaborators && post.collaborators.length > 0) ? true : false,
                    collaborators: post.collaborators,
                    taggedUsers: post.tagged_users,
                    // 🔥 BULLETPROOF DATE HANDLER:
                    // If it's a number (seconds), multiply by 1000. If it's an ISO string, use it directly.
                    postedAt: post.timestamp 
                        ? new Date(typeof post.timestamp === 'number' ? post.timestamp * 1000 : post.timestamp) 
                        : new Date()
                },
                // 🚀 CHANGED: Fixed Mongoose warning (new -> returnDocument)
                { upsert: true, returnDocument: 'after' } 
            );

            // Accumulate Totals
            totalLikes += (post.like_count || 0);
            totalComments += (post.comments_count || 0);
            if (post.media_type === 'VIDEO') {
                totalPlays += (post.play_count || 0);
                reelCount++;
            } else {
                imageCount++;
            }

            // 🚀 CHANGED: Safety fallback added to prevent .filter crash
            const collabs = (post.collaborators || []).filter(u => u !== brandUsername);
            
            for (const collab of collabs) {
                if (!collabStats[collab]) {
                    collabStats[collab] = { count: 0, reels: 0, images: 0, likes: 0, plays: 0 };
                }
                collabStats[collab].count++;
                collabStats[collab].likes += (post.like_count || 0);
                if (post.media_type === 'VIDEO') {
                    collabStats[collab].reels++;
                    collabStats[collab].plays += (post.play_count || 0);
                } else {
                    collabStats[collab].images++;
                }
            }
        }

        // 3. Save Collaboration Graphs
        console.log(`🤝 Updating ${Object.keys(collabStats).length} Collaborator Graphs...`);
        const sortedCollabs = [];
        for (const [collabUser, stats] of Object.entries(collabStats)) {
            await RadarCollaboration.findOneAndUpdate(
                { brandUsername, collaboratorUsername: collabUser },
                {
                    metrics: {
                        totalCollaborations: stats.count,
                        totalReels: stats.reels,
                        totalImages: stats.images,
                        avgLikesGenerated: Math.round(stats.likes / stats.count),
                        avgPlaysGenerated: stats.reels > 0 ? Math.round(stats.plays / stats.reels) : 0,
                    },
                    lastCollaboratedAt: new Date() 
                },
                { upsert: true }
            );
            sortedCollabs.push({ username: collabUser, collaborationCount: stats.count });
        }

        // 4. Calculate Final Brand Insights
        // 4. 🧠 Calculate Derived Intelligence Insights
        console.log(`🧠 Calculating Advanced Intelligence...`);
        const totalProcessed = enrichedPosts.length || 1;
        const followers = profile.followers_count || 1;
        
        const avgLikes = Math.round(totalLikes / totalProcessed);
        const avgComments = Math.round(totalComments / totalProcessed);
        const er = parseFloat((((avgLikes + avgComments) / followers) * 100).toFixed(2));

        // 🔥 ENGAGEMENT CONSISTENCY (Standard Deviation of Likes)
        const likesArray = enrichedPosts.map(p => p.like_count || 0);
        const variance = likesArray.reduce((acc, val) => acc + Math.pow(val - avgLikes, 2), 0) / totalProcessed;
        const consistencyScore = Math.round(Math.sqrt(variance)); 

        // 🔥 POSTING TIME OPTIMIZATION (Hour & Day)
        const hoursCount = {};
        const daysCount = {};
        enrichedPosts.forEach(p => {
            const dateObj = new Date(p.timestamp || p.postedAt || Date.now());
            const hour = dateObj.getHours();
            const day = dateObj.getDay();
            hoursCount[hour] = (hoursCount[hour] || 0) + 1;
            daysCount[day] = (daysCount[day] || 0) + 1;
        });
        const topPostingHour = Object.keys(hoursCount).reduce((a, b) => hoursCount[a] > hoursCount[b] ? a : b, 0);
        const topPostingDay = Object.keys(daysCount).reduce((a, b) => daysCount[a] > daysCount[b] ? a : b, 0);

        // 🔥 CONTENT FORMULA ENGINE (Hashtags & Mentions)
        const hashtagMap = {};
        const mentionMap = {};
        enrichedPosts.forEach(p => {
            (p.hashtags || []).forEach(tag => { hashtagMap[tag] = (hashtagMap[tag] || 0) + 1; });
            (p.mentions || []).forEach(tag => { mentionMap[tag] = (mentionMap[tag] || 0) + 1; });
        });
        const topHashtags = Object.entries(hashtagMap).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([tag]) => tag);
        const topMentions = Object.entries(mentionMap).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([tag]) => tag);

        // 🔥 COLLABORATION IMPACT (Lift)
        let collabLikes = 0, collabCount = 0, normalLikes = 0, normalCount = 0;
        enrichedPosts.forEach(p => {
            if (p.isCollaboration) {
                collabLikes += p.like_count || 0;
                collabCount++;
            } else {
                normalLikes += p.like_count || 0;
                normalCount++;
            }
        });
        const collabAvg = collabLikes / (collabCount || 1);
        const normalAvg = normalLikes / (normalCount || 1);
        const collabLift = normalAvg > 0 ? ((collabAvg - normalAvg) / normalAvg) * 100 : 0;

        // 🔥 GROWTH TREND (First Half vs Second Half)
        const sortedByTime = [...enrichedPosts].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        const midPoint = Math.floor(totalProcessed / 2);
        const firstHalf = sortedByTime.slice(0, midPoint);
        const secondHalf = sortedByTime.slice(midPoint);
        const avgFirst = firstHalf.reduce((acc, p) => acc + (p.like_count || 0), 0) / (firstHalf.length || 1);
        const avgSecond = secondHalf.reduce((acc, p) => acc + (p.like_count || 0), 0) / (secondHalf.length || 1);
        const growthRate = avgFirst > 0 ? ((avgSecond - avgFirst) / avgFirst) * 100 : 0;

        // 🔥 TOP POSTS RANKING (By Virality)
        const topPosts = [...enrichedPosts]
            .sort((a, b) => (b.metrics?.viralityScore || 0) - (a.metrics?.viralityScore || 0))
            .slice(0, 10)
            .map(p => ({
                shortcode: p.shortcode || '',
                mediaUrl: p.media_url || '',
                type: p.media_type || 'IMAGE',
                viralityScore: p.metrics?.viralityScore || 0, // 🚀 FIX: Fallback to 0 instead of undefined
                likes: p.like_count || 0 // 🚀 FIX: Fallback to 0
            }));

        const topCollabs = sortedCollabs.sort((a, b) => b.collaborationCount - a.collaborationCount).slice(0, 15);

        // 5. Upsert the upgraded Dashboard Document
        await BrandRadar.findOneAndUpdate(
            { brandUsername },
            {
                name: profile.name,
                profilePic: profile.profile_picture_url,
                biography: profile.biography,
                stats: {
                    followers: profile.followers_count,
                    following: profile.follows_count,
                    totalPosts: profile.media_count,
                },
                insights: {
                    analyzedPostCount: totalProcessed,
                    avgLikes,
                    avgComments,
                    avgPlays: reelCount > 0 ? Math.round(totalPlays / reelCount) : 0,
                    engagementRate: er,
                    consistencyScore,
                    topPostingHour: Number(topPostingHour),
                    topPostingDay: Number(topPostingDay), // 🚀 NEW
                    collaborationLift: Number(collabLift.toFixed(2)), // 🚀 NEW
                    growthRate: Number(growthRate.toFixed(2)), // 🚀 NEW
                    topHashtags, // 🚀 NEW
                    topMentions, // 🚀 NEW
                    contentSplit: {
                        reelsPercentage: parseFloat(((reelCount / totalProcessed) * 100).toFixed(1)),
                        imagePercentage: parseFloat(((imageCount / totalProcessed) * 100).toFixed(1)),
                    },
                    bestPerformingType: reelCount > imageCount ? "VIDEO" : "IMAGE"
                },
                topPosts, // 🚀 NEW: Storing the top 10 most viral posts
                topCollaborators: topCollabs,
                lastSyncedAt: new Date()
            },
            { upsert: true }
        );

        queueItem.status = 'completed';
        queueItem.processedAt = new Date();
        await queueItem.save();
        console.log(`✅ Successfully mapped Radar for @${brandUsername}`);

    } catch (err) {
        console.error(`❌ Failed to process @${brandUsername}:`, err.message);
        queueItem.status = 'failed';
        queueItem.errorLog = err.message;
        await queueItem.save();
    }
}

// --- WORKER LOOP ---
async function startWorker() {
    await connectDB();
    console.log('👷 Radar Worker Started. Listening for tasks...');

    while (true) {
        try {
            const task = await RadarQueue.findOne({ status: 'pending' }).sort({ addedAt: 1 });
            if (task) {
                await processBrand(task);
            } else {
                await sleep(SLEEP_MS);
            }
        } catch (err) {
            console.error('🚨 Fatal Worker Error:', err);
            await sleep(SLEEP_MS);
        }
    }
}

startWorker();