const mongoose = require('mongoose');

const RadarCollaborationSchema = new mongoose.Schema({
    brandUsername: { type: String, required: true, index: true },
    collaboratorUsername: { type: String, required: true, index: true },
    
    metrics: {
        totalCollaborations: { type: Number, default: 0 },
        totalReels: { type: Number, default: 0 },
        totalImages: { type: Number, default: 0 },
        
        avgLikesGenerated: { type: Number, default: 0 },
        avgPlaysGenerated: { type: Number, default: 0 },
    },
    
    lastCollaboratedAt: Date
}, { timestamps: true });

// Prevent duplicate mappings
RadarCollaborationSchema.index({ brandUsername: 1, collaboratorUsername: 1 }, { unique: true });

module.exports = mongoose.model('RadarCollaboration', RadarCollaborationSchema);