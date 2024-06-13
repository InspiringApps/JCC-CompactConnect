//
//  babel.config.js
//  InspiringApps modules
//
//  Created by InspiringApps on 04/27/2021.
//  Copyright © 2024. InspiringApps. All rights reserved.
//

module.exports = {
    presets: [
        '@vue/cli-plugin-babel/preset',
    ],
    env: {
        test: {
            plugins: [
                [ 'istanbul' ]
            ]
        }
    }
};
