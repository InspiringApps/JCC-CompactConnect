//
//  HomeState.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import chaiMatchPattern from 'chai-match-pattern';
import { use, expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import HomeState from '@pages/Applications/HomeState/HomeState.vue';
import { CompactSerializer, CompactType } from '@models/Compact/Compact.model';
import { ApplicationSection } from '@models/Application/Application.model';
import { dataApi as mockDataApi } from '@network/mocks/mock.data.api';
import store from '@store/index';
import { nextTick } from 'vue';
import { flushPromises } from '@vue/test-utils';

use(chaiMatchPattern);

const apitAttestationKey = 'homeState-apit-comply-with-state-requirements';

const mountPage = async (applicationId: string, mountFn = mountFull) => {
    const wrapper = await mountFn(HomeState);
    const component = wrapper.vm;

    await flushPromises();
    await component.$router.push({
        name: 'ApplicationHomeState',
        params: { compact: CompactType.PSYPACT, applicationId },
    });
    await component.fetchApplication();
    await nextTick();

    return wrapper;
};

describe('HomeState page', async () => {
    beforeEach(async () => {
        await store.dispatch('user/setCurrentCompact', CompactSerializer.fromServer({ type: CompactType.PSYPACT }));
    });
    afterEach(() => {
        mockDataApi.resetCreatedApplications();
    });
    it('should mount the page component', async () => {
        const wrapper = await mountShallow(HomeState);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(HomeState).exists()).to.equal(true);
    });
    it('should mock populate a valid form, scroll to the save button, and clear the form', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.handleMockPopulate();

        expect(component.isFormValid).to.equal(true);
        expect(scrollStub.calledOnceWith(component.formData.submit.id)).to.equal(true);

        await component.handleClearForm();

        component.homeStateSections.forEach(({ type }) => {
            expect(component.formInputFor(type, 'State').value).to.equal('');
            expect(component.formInputFor(type, 'IsActiveMilitary').value).to.equal(false);
        });
        expect(component.isFormValid).to.equal(false);
    });
    it('should only display the home state sections for the application types', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        expect(component.sectionKey).to.equal(ApplicationSection.HOME_STATE);
        expect(wrapper.find('.section-title').text()).to.equal('Home state declaration');
        expect(wrapper.findAll('.home-state-section').length).to.equal(1);
        expect(wrapper.find('.home-state-apit .card-title').text()).to.equal('APIT home state');
        expect(wrapper.find('.home-state-tap').exists()).to.equal(false);
        expect(component.formData.apitState.value).to.equal('');
        expect(component.formData[apitAttestationKey].value).to.equal(false);
        expect(wrapper.find('.policy-link').exists()).to.equal(true);
    });
    it('should display a section per application type with its own acknowledgement', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        expect(wrapper.findAll('.home-state-section').length).to.equal(2);
        expect(wrapper.find('.home-state-tap .card-title').text()).to.equal('TAP home state');
        expect(component.formData.apitState.value).to.equal('co');
        expect(component.formData.tapState.value).to.equal('ky');
        expect(component.formData[apitAttestationKey].value).to.equal(true);
        expect(component.formData['homeState-tap-comply-with-state-requirements'].value).to.equal(true);
    });
    it('should hide home state entries that are not one of the application types', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;

        component.fetchedApplication.types = ['tap'];

        expect(component.homeStateSections.map((section) => section.type)).to.matchPattern(['tap']);
    });
    it('should require military documents when declaring under active-duty orders', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        expect(wrapper.find('.military-documents').exists()).to.equal(false);

        await wrapper.find('#apit-is-active-military').setValue(true);
        await nextTick();

        expect(component.isActiveMilitary('apit')).to.equal(true);
        expect(wrapper.find('.home-state-apit .military-documents').exists()).to.equal(true);

        component.validateAll({ asTouched: true, skipErrorScroll: true });

        expect(component.isFormValid).to.equal(false);
        expect(component.formData.apitMilitaryDocuments.errorMessage).to.equal('Required field');

        await wrapper.find('#apit-is-active-military').setValue(false);
        await nextTick();

        expect(component.formData.apitMilitaryDocuments.isValid).to.equal(true);
    });
    it('should not require new military documents when some were already uploaded', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;

        component.existingDocuments.apit = [{ filename: 'orders.pdf', sizeBytes: 100 }];
        component.formData.apitIsActiveMilitary.value = true;
        component.onActiveMilitaryChange('apit');

        expect(component.formData.apitMilitaryDocuments.isValid).to.equal(true);

        component.removeExistingDocument('apit', component.existingDocuments.apit[0]);
        component.formData.apitMilitaryDocuments.isTouched = true;
        component.formData.apitMilitaryDocuments.validate();

        expect(component.formData.apitMilitaryDocuments.isValid).to.equal(false);
    });
    it('should require the home state acknowledgement', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;

        component.validateAll({ asTouched: true, skipErrorScroll: true });

        expect(component.formData[apitAttestationKey].errorMessage).to.equal('Required');
        expect(component.formData.apitState.errorMessage).to.equal('Required field');
    });
    it('should upload military documents and prep the section request data', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;
        const newFile = new File(['orders'], 'orders.pdf', { type: 'application/pdf' });

        formData.apitIsActiveMilitary.value = true;
        formData.apitMilitaryDocuments.value = [newFile];
        formData.tapState.value = 'ne';
        formData.tapMilitaryDocuments.value = [newFile];

        const requestData: any = await component.prepSectionRequestData();

        expect(requestData).to.matchPattern({
            applicationTypes: [
                {
                    applicationType: 'apit',
                    state: 'co',
                    startDate: component.sectionData.applicationTypes[0].startDate,
                    isActiveMilitary: true,
                    militaryDocuments: [{ filename: 'orders.pdf', sizeBytes: newFile.size }],
                    attestations: [{
                        attestationId: 'comply-with-state-requirements',
                        version: '1',
                        value: true,
                    }],
                },
                {
                    applicationType: 'tap',
                    state: 'ne',
                    startDate: component.sectionData.applicationTypes[1].startDate,
                    isActiveMilitary: false,
                    militaryDocuments: [],
                    attestations: [{
                        attestationId: 'comply-with-state-requirements',
                        version: '1',
                        value: true,
                    }],
                },
            ],
        });
    });
    it('should save the section and route to acknowledgements next', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');

        component.formData.tapState.value = 'ne';
        await component.handleSubmit();
        dispatchSpy.restore();

        expect(dispatchSpy.calledWith('user/updateApplicationRequestLicensee')).to.equal(true);
        expect(component.isFormSuccessful).to.equal(true);
        expect(component.application.homeState.applicationTypes[1].state).to.equal('ne');
        expect(component.nextRoute).to.matchPattern({
            name: 'ApplicationAcknowledgements',
            params: { compact: CompactType.PSYPACT, applicationId: '2' },
        });
    });
});
