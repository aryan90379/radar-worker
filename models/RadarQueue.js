const mongoose = require('mongoose');

const RadarQueueSchema = new mongoose.Schema({
    brandUsername: { type: String, required: true, unique: true, index: true },
    targetPosts: { type: Number, default: 200 }, // Tells worker how many to scrape
    status: { type: String, enum: ['pending', 'processing', 'completed', 'failed'], default: 'pending' },
    attempts: { type: Number, default: 0 },
    errorLog: { type: String },
    addedAt: { type: Date, default: Date.now },
    processedAt: { type: Date }
});

module.exports = mongoose.model('RadarQueue', RadarQueueSchema);