const mongoose = require('mongoose');

const RadarPostSchema = new mongoose.Schema({
    brandUsername: { type: String, required: true, index: true },
    shortcode: { type: String, required: true, unique: true },
    mediaId: String,
    
    type: { type: String, enum: ['VIDEO', 'IMAGE', 'CAROUSEL'] },
    caption: String,
    mediaUrl: String,
    permalink: String,

    metrics: {
        likes: { type: Number, default: 0 },
        comments: { type: Number, default: 0 },
        plays: { type: Number, default: 0 },
        viralityScore: { type: Number, default: 0 }, // 🚀 NEW
    },

    // 🚀 NEW: Content Intelligence
    hashtags: [{ type: String }],
    mentions: [{ type: String }],
    isCollaboration: { type: Boolean, default: false },

    collaborators: [{ type: String }], // Array of usernames
    taggedUsers: [{ type: String }],

    postedAt: Date,
}, { timestamps: true });

module.exports = mongoose.model('RadarPost', RadarPostSchema);