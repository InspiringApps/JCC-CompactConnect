//
//  AppMessage.ts
//  inHere
//
//  Created by InspiringApps on 6/1/2020.
//  //  Copyright © 2024. InspiringApps. All rights reserved.
//

// ========================================================
// =                       Interface                      =
// ========================================================
export const enum MessageTypes {
    info = 'info',
    success = 'success',
    error = 'error'
}

export interface InterfaceAppMessageCreate {
    type?: MessageTypes;
    message?: string;
}

// ========================================================
// =                        Model                         =
// ========================================================
export class AppMessage implements InterfaceAppMessageCreate {
    public type = MessageTypes.info;
    public message = '';

    constructor(data?: InterfaceAppMessageCreate) {
        Object.assign(this, data);
    }
}
