//
//  ExampleModal.spec.ts
//  InspiringApps modules
//
//  Created by InspiringApps on 5/4/2021.
//  Copyright © 2024. InspiringApps. All rights reserved.
//

import { expect } from 'chai';
import { mountShallow } from '@tests/helpers/setup';
import ExampleModal from '@components/StyleGuide/ExampleModal/ExampleModal.vue';

describe('ExampleModal component', async () => {
    it('should mount the component', async () => {
        const wrapper = await mountShallow(ExampleModal);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(ExampleModal).exists()).to.equal(true);
    });
});
