const mongoose = require('mongoose');

const BrandRadarSchema = new mongoose.Schema({
    brandUsername: { type: String, required: true, unique: true, index: true },
    name: String,
    profilePic: String,
    biography: String,

    stats: {
        followers: Number,
        following: Number,
        totalPosts: Number,
    },

    // 🔥 Precomputed Insights for the Frontend Dashboard
    insights: {
        analyzedPostCount: Number,
        avgLikes: Number,
        avgComments: Number,
        avgPlays: Number, 
        engagementRate: Number,

        // 🚀 NEW: Advanced Intelligence
        consistencyScore: Number,
        topPostingHour: Number,
        topPostingDay: Number,
        collaborationLift: Number,
        growthRate: Number,
        topHashtags: [{ type: String }],
        topMentions: [{ type: String }],
        
        contentSplit: {
            reelsPercentage: Number,
            imagePercentage: Number,
        },
        
        bestPerformingType: String, // "VIDEO" or "IMAGE"
    },

    // 🚀 NEW: Hall of Fame
   // 🚀 NEW: Hall of Fame
    topPosts: [{
        shortcode: String,
        mediaUrl: String,
        type: { type: String }, // ✅ FIXED: Tells Mongoose the field name is "type" and its value is a String
        viralityScore: Number,
        likes: Number
    }],

    topCollaborators: [{
        username: String,
        collaborationCount: Number
    }],

    lastSyncedAt: { type: Date, default: Date.now }
}, { timestamps: true });

module.exports = mongoose.model('BrandRadar', BrandRadarSchema);