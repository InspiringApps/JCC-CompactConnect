//
//  AuthorizationCard.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/10/2026.
//

import { expect } from 'chai';
import { mountShallow } from '@tests/helpers/setup';
import AuthorizationCard from '@components/AuthorizationCard/AuthorizationCard.vue';
import InputButton from '@components/Forms/InputButton/InputButton.vue';
import { serverDateFormat } from '@/app.config';
import { Authorization, AuthorizationStatus } from '@models/Authorization/Authorization.model';
import { ApplicationType } from '@models/Application/Application.model';
import moment from 'moment';

describe('AuthorizationCard component', async () => {
    it('should mount the component', async () => {
        const wrapper = await mountShallow(AuthorizationCard, {
            props: {
                authorizationType: ApplicationType.APIT,
            },
        });

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(AuthorizationCard).exists()).to.equal(true);
    });
    it('should display an active authorization without an apply button', async () => {
        const authorization = new Authorization({
            type: ApplicationType.APIT,
            status: AuthorizationStatus.ACTIVE,
            expireDate: moment().add(1, 'year').format(serverDateFormat),
        });
        const wrapper = await mountShallow(AuthorizationCard, {
            props: {
                authorizationType: ApplicationType.APIT,
                authorization,
            },
        });
        const component = wrapper.vm;

        expect(component.isActive).to.equal(true);
        expect(component.title).to.equal('APIT Authorization');
        expect(component.statusDisplay).to.equal('Active');
        expect(component.expireDateDisplay).to.equal(authorization.expireDateDisplay());
        expect(wrapper.find('.authorization-card-container.active').exists()).to.equal(true);
        expect(wrapper.findComponent(InputButton).exists()).to.equal(false);
    });
    it('should display an apply button when the authorization does not exist', async () => {
        const wrapper = await mountShallow(AuthorizationCard, {
            props: {
                authorizationType: ApplicationType.TAP,
            },
        });
        const component = wrapper.vm;

        expect(component.isActive).to.equal(false);
        expect(component.title).to.equal('TAP Authorization');
        expect(component.description).to.equal('Short-term, in-person practice in another participating state.');
        expect(component.isExpiredDateDisplayed).to.equal(false);
        expect(wrapper.find('.authorization-card-container.apply').exists()).to.equal(true);
        expect(wrapper.findComponent(InputButton).exists()).to.equal(true);
    });
    it('should display an apply button when the authorization is expired', async () => {
        const wrapper = await mountShallow(AuthorizationCard, {
            props: {
                authorizationType: ApplicationType.APIT,
                authorization: new Authorization({
                    type: ApplicationType.APIT,
                    status: AuthorizationStatus.ACTIVE,
                    expireDate: moment().subtract(1, 'day').format(serverDateFormat),
                }),
            },
        });
        const component = wrapper.vm;

        expect(component.isActive).to.equal(false);
        expect(component.isExpiredDateDisplayed).to.equal(true);
        expect(wrapper.find('.authorization-expired').exists()).to.equal(true);
        expect(wrapper.findComponent(InputButton).exists()).to.equal(true);
    });
    it('should display an apply button when the authorization is inactive', async () => {
        const wrapper = await mountShallow(AuthorizationCard, {
            props: {
                authorizationType: ApplicationType.APIT,
                authorization: new Authorization({
                    type: ApplicationType.APIT,
                    status: AuthorizationStatus.INACTIVE,
                    expireDate: moment().add(1, 'year').format(serverDateFormat),
                }),
            },
        });
        const component = wrapper.vm;

        expect(component.isActive).to.equal(false);
        expect(component.isExpiredDateDisplayed).to.equal(false);
        expect(wrapper.findComponent(InputButton).exists()).to.equal(true);
    });
});
