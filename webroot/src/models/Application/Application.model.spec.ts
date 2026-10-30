//
//  Application.model.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 10/29/2026.
//

import { expect } from 'chai';
import { Application } from '@models/Application/Application.model';

describe('Application model', () => {
    it('should create a Application', () => {
        const application = new Application();

        expect(application).to.be.an.instanceof(Application);
    });
});
